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
const envPath = path.join(baseDir, "config", "mcp", "docs-mcp.env");
if (fs.existsSync(envPath)) {
  dotenv.config({ path: envPath });
} else {
  dotenv.config(); // fallback to default .env
}

// Initialize Google Docs API client
function getDocsClient() {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  const refreshToken = process.env.GOOGLE_REFRESH_TOKEN;

  if (!clientId || !clientSecret || !refreshToken) {
    console.error("Missing Google credentials in environment config.");
    throw new Error("Missing Google credentials in environment config.");
  }

  const oauth2Client = new google.auth.OAuth2(clientId, clientSecret);
  oauth2Client.setCredentials({ refresh_token: refreshToken });

  return google.docs({ version: "v1", auth: oauth2Client });
}

const server = new Server(
  {
    name: "google-docs-mcp",
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
        name: "find_section_by_anchor",
        description: "Checks if a specific weekly section exists in the document based on an anchor string (e.g. groww-2026-W23).",
        inputSchema: {
          type: "object",
          properties: {
            document_id: { type: "string", description: "Google Doc ID" },
            anchor: { type: "string", description: "The section anchor key (e.g. groww-2026-W23)" }
          },
          required: ["document_id", "anchor"]
        }
      },
      {
        name: "append_section",
        description: "Appends a new styled section (weekly report) to the Google Document.",
        inputSchema: {
          type: "object",
          properties: {
            document_id: { type: "string", description: "Google Doc ID" },
            anchor: { type: "string", description: "Unique anchor text for idempotency" },
            blocks: {
              type: "array",
              description: "Array of text blocks to append",
              items: {
                type: "object",
                properties: {
                  type: { type: "string", enum: ["heading1", "heading2", "paragraph", "list_item"] },
                  text: { type: "string" }
                },
                required: ["type", "text"]
              }
            }
          },
          required: ["document_id", "anchor", "blocks"]
        }
      },
      {
        name: "get_document_url",
        description: "Resolves a shareable link to the document, optionally deep-linking to a specific heading ID.",
        inputSchema: {
          type: "object",
          properties: {
            document_id: { type: "string", description: "Google Doc ID" },
            heading_id: { type: "string", description: "Optional heading ID for deep linking" }
          },
          required: ["document_id"]
        }
      }
    ]
  };
});

// Handle tool executions
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const docs = getDocsClient();

  try {
    if (name === "find_section_by_anchor") {
      const { document_id, anchor } = args as { document_id: string; anchor: string };
      const doc = await docs.documents.get({ documentId: document_id });
      const content = doc.data.body?.content || [];

      for (const element of content) {
        if (element.paragraph) {
          const text = element.paragraph.elements?.map((el) => el.textRun?.content).join("") || "";
          if (text.includes(anchor)) {
            const headingId = element.paragraph.paragraphStyle?.headingId;
            return {
              content: [
                {
                  type: "text",
                  text: JSON.stringify({
                    found: true,
                    heading_id: headingId || "",
                    url_fragment: headingId ? `#heading=${headingId}` : ""
                  })
                }
              ]
            };
          }
        }
      }

      return {
        content: [{ type: "text", text: JSON.stringify({ found: false }) }]
      };

    } else if (name === "append_section") {
      const { document_id, anchor, blocks } = args as {
        document_id: string;
        anchor: string;
        blocks: Array<{ type: "heading1" | "heading2" | "paragraph" | "list_item"; text: string }>;
      };

      // 1. Fetch document length/structure
      const initialDoc = await docs.documents.get({ documentId: document_id });
      const content = initialDoc.data.body?.content || [];
      const lastElement = content.slice(-1)[0];
      const insertIndex = lastElement?.endIndex ? lastElement.endIndex - 1 : 1;

      // 2. Format blocks into a single string while mapping offsets
      let concatenatedText = "";
      const blockIntervals: Array<{ type: string; start: number; end: number }> = [];

      for (const block of blocks) {
        const start = concatenatedText.length;
        let blockText = block.text;

        if (block.type === "list_item") {
          blockText = `• ${blockText}`;
        }
        concatenatedText += `${blockText}\n`;
        const end = concatenatedText.length;

        blockIntervals.push({
          type: block.type,
          start,
          end
        });
      }

      // Add a newline at the very end to separate sections
      concatenatedText += "\n";

      // 3. Construct batchUpdate requests
      const requests: any[] = [
        // A. Insert all text at the end of the document
        {
          insertText: {
            location: { index: insertIndex },
            text: concatenatedText
          }
        }
      ];

      // B. Apply block styles (in reverse order to keep offsets correct, or using the offset calculations)
      // Since all formatting is applied relative to the document indices *after* the text is inserted,
      // we must compute final document index: finalIndex = insertIndex + offset.
      for (const block of blockIntervals) {
        const startDocIdx = insertIndex + block.start;
        const endDocIdx = insertIndex + block.end;

        let styleName = "NORMAL_TEXT";
        if (block.type === "heading1") styleName = "HEADING_1";
        if (block.type === "heading2") styleName = "HEADING_2";

        requests.push({
          updateParagraphStyle: {
            range: {
              startIndex: startDocIdx,
              endIndex: endDocIdx
            },
            paragraphStyle: {
              namedStyleType: styleName
            },
            fields: "namedStyleType"
          }
        });

        // Add styling triggers (e.g. bolding list item prefix or headers)
        if (block.type === "heading1" || block.type === "heading2") {
          requests.push({
            updateTextStyle: {
              range: {
                startIndex: startDocIdx,
                endIndex: endDocIdx - 1 // ignore trailing newline
              },
              textStyle: {
                bold: true,
                foregroundColor: {
                  color: {
                    rgbColor: block.type === "heading1" ? { red: 0.1, green: 0.1, blue: 0.3 } : { red: 0.2, green: 0.2, blue: 0.2 }
                  }
                }
              },
              fields: "bold,foregroundColor"
            }
          });
        }
      }

      // Execute writes
      await docs.documents.batchUpdate({
        documentId: document_id,
        requestBody: { requests }
      });

      // 4. Retrieve heading ID of the heading block just created
      const updatedDoc = await docs.documents.get({ documentId: document_id });
      const updatedContent = updatedDoc.data.body?.content || [];
      let finalHeadingId = "";

      for (const element of updatedContent) {
        if (element.paragraph) {
          const text = element.paragraph.elements?.map((el) => el.textRun?.content).join("") || "";
          if (text.includes(anchor)) {
            finalHeadingId = element.paragraph.paragraphStyle?.headingId || "";
            break;
          }
        }
      }

      const docUrl = `https://docs.google.com/document/d/${document_id}/edit${finalHeadingId ? `#heading=${finalHeadingId}` : ""}`;

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              heading_id: finalHeadingId,
              revision_id: updatedDoc.data.revisionId || "",
              url: docUrl
            })
          }
        ]
      };

    } else if (name === "get_document_url") {
      const { document_id, heading_id } = args as { document_id: string; heading_id?: string };
      const url = `https://docs.google.com/document/d/${document_id}/edit${heading_id ? `#heading=${heading_id}` : ""}`;
      return {
        content: [{ type: "text", text: JSON.stringify({ url }) }]
      };
    }

    throw new Error(`Tool not found: ${name}`);
  } catch (error: any) {
    console.error(`Error in google-docs-mcp server tool ${name}:`, error);
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
  console.error("Google Docs MCP Server running on stdio transport.");
}

run().catch((error) => {
  console.error("Fatal error starting Google Docs MCP Server:", error);
  process.exit(1);
});
