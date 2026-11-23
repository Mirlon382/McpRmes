# MCP Rmes 🦴

Python MCP server based on the FastMCP v4 lib to connect LLM to the SPARQL enabled endpoint of RMeS, the INSEE ontology.

## Run locally

Simply retrieve the repository. UV handles the rest.

```{bash}
git clone <url>
uv sync
uv run mcpserver
```

To inspect and test the server without using an LLM

```{bash}
npx @modelcontextprotocol/inspector
```

## Make it portable

To deploy the server 

```{bash}
docker build . -t myserver
```

There is also some Kubernetes config available in `k8s/`
