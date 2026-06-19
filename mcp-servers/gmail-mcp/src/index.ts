import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { google } from "googleapis";
import * as dotenv from "dotenv";
import * as path from "path";
import * as fs from "fs";

// Load environment variables
const baseDir = process.cwd();
const envPath = path.join(baseDir, "config", "mcp", "gmail-mcp.env");
if (fs.existsSync(envPath)) {
  dotenv.config({ path: envPath });
} else {
  dotenv.config(); // fallback to default .env
}

const ledgerPath = path.join(baseDir, "data", "cache", "gmail_ledger.json");

// Helper to interact with the Gmail ledger
function checkIdempotencyInLedger(key: string): { already_sent: boolean; message_id?: string } {
  if (!fs.existsSync(ledgerPath)) {
    return { already_sent: false };
  }
  try {
    const data = JSON.parse(fs.readFileSync(ledgerPath, "utf8"));
    if (data[key]) {
      return { already_sent: true, message_id: data[key] };
    }
  } catch (error) {
    console.error("Failed to read Gmail ledger:", error);
  }
  return { already_sent: false };
}

function recordIdempotencyInLedger(key: string, id: string): void {
  let data: Record<string, string> = {};
  const dir = path.dirname(ledgerPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  if (fs.existsSync(ledgerPath)) {
    try {
      data = JSON.parse(fs.readFileSync(ledgerPath, "utf8"));
    } catch (error) {
      console.error("Failed to read Gmail ledger for write:", error);
    }
  }

  data[key] = id;
  fs.writeFileSync(ledgerPath, JSON.stringify(data, null, 2), "utf8");
}

// Initialize Google Gmail API client
function getGmailClient() {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  const refreshToken = process.env.GOOGLE_REFRESH_TOKEN;

  if (!clientId || !clientSecret || !refreshToken) {
    console.error("Missing Google credentials in environment config.");
    throw new Error("Missing Google credentials in environment config.");
  }

  const oauth2Client = new google.auth.OAuth2(clientId, clientSecret);
  oauth2Client.setCredentials({ refresh_token: refreshToken });

  return google.gmail({ version: "v1", auth: oauth2Client });
}

// Helper to construct RFC 822 base64url encoded MIME message
function buildMimeMessage(to: string[], subject: string, htmlBody: string, textBody: string): string {
  const boundary = "__boundary_marker__";
  const nl = "\r\n";
  const parts = [
    `To: ${to.join(", ")}`,
    `Subject: ${subject}`,
    `MIME-Version: 1.0`,
    `Content-Type: multipart/alternative; boundary="${boundary}"`,
    "",
    `--${boundary}`,
    `Content-Type: text/plain; charset="UTF-8"`,
    `Content-Transfer-Encoding: 7bit`,
    "",
    textBody,
    "",
    `--${boundary}`,
    `Content-Type: text/html; charset="UTF-8"`,
    `Content-Transfer-Encoding: 7bit`,
    "",
    htmlBody,
    "",
    `--${boundary}--`
  ];
  const mime = parts.join(nl);
  // Gmail API requires base64url format
  return Buffer.from(mime)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

const server = new Server(
  {
    name: "gmail-mcp",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Define tool schema
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "check_idempotency",
        description: "Checks if an email with the specified idempotency key has already been sent/created.",
        inputSchema: {
          type: "object",
          properties: {
            idempotency_key: { type: "string", description: "The email idempotency key (e.g. groww-2026-W23-email)" }
          },
          required: ["idempotency_key"]
        }
      },
      {
        name: "create_draft",
        description: "Creates an email draft in the user's Gmail box, validating idempotency keys first.",
        inputSchema: {
          type: "object",
          properties: {
            to: {
              type: "array",
              description: "Array of recipient email addresses",
              items: { type: "string" }
            },
            subject: { type: "string" },
            html_body: { type: "string", description: "HTML content for the email body" },
            text_body: { type: "string", description: "Plain text fallback content" },
            idempotency_key: { type: "string", description: "Idempotency key for validation" }
          },
          required: ["to", "subject", "html_body", "text_body", "idempotency_key"]
        }
      },
      {
        name: "send_email",
        description: "Sends an email to stakeholders via Gmail, validating idempotency keys first.",
        inputSchema: {
          type: "object",
          properties: {
            to: {
              type: "array",
              description: "Array of recipient email addresses",
              items: { type: "string" }
            },
            subject: { type: "string" },
            html_body: { type: "string", description: "HTML content for the email body" },
            text_body: { type: "string", description: "Plain text fallback content" },
            idempotency_key: { type: "string", description: "Idempotency key for validation" }
          },
          required: ["to", "subject", "html_body", "text_body", "idempotency_key"]
        }
      }
    ]
  };
});

// Handle tool executions
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const gmail = getGmailClient();

  try {
    if (name === "check_idempotency") {
      const { idempotency_key } = args as { idempotency_key: string };
      const status = checkIdempotencyInLedger(idempotency_key);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(status)
          }
        ]
      };

    } else if (name === "create_draft") {
      const { to, subject, html_body, text_body, idempotency_key } = args as {
        to: string[];
        subject: string;
        html_body: string;
        text_body: string;
        idempotency_key: string;
      };

      const check = checkIdempotencyInLedger(idempotency_key);
      if (check.already_sent) {
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                status: "skipped",
                reason: "Idempotency key already exists",
                draft_id: check.message_id
              })
            }
          ]
        };
      }

      const raw = buildMimeMessage(to, subject, html_body, text_body);
      const res = await gmail.users.drafts.create({
        userId: "me",
        requestBody: {
          message: {
            raw
          }
        }
      });

      const draftId = res.data.id || "";
      recordIdempotencyInLedger(idempotency_key, draftId);

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              status: "success",
              draft_id: draftId
            })
          }
        ]
      };

    } else if (name === "send_email") {
      const { to, subject, html_body, text_body, idempotency_key } = args as {
        to: string[];
        subject: string;
        html_body: string;
        text_body: string;
        idempotency_key: string;
      };

      const check = checkIdempotencyInLedger(idempotency_key);
      if (check.already_sent) {
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                status: "skipped",
                reason: "Idempotency key already exists",
                message_id: check.message_id
              })
            }
          ]
        };
      }

      const raw = buildMimeMessage(to, subject, html_body, text_body);
      const res = await gmail.users.messages.send({
        userId: "me",
        requestBody: {
          raw
        }
      });

      const msgId = res.data.id || "";
      recordIdempotencyInLedger(idempotency_key, msgId);

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              status: "success",
              message_id: msgId
            })
          }
        ]
      };
    }

    throw new Error(`Tool not found: ${name}`);
  } catch (error: any) {
    console.error(`Error in gmail-mcp server tool ${name}:`, error);
    return {
      isError: true,
      content: [{ type: "text", text: error.message || String(error) }]
    };
  }
});

// Start the server
async function run() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Gmail MCP Server running on stdio transport.");
}

run().catch((error) => {
  console.error("Fatal error starting Gmail MCP Server:", error);
  process.exit(1);
});
