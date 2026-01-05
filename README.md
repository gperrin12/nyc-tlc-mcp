# NYC TLC Athena MCP Server + Claude Skill

Query your NYC Taxi & Limousine Commission data in AWS Athena using natural language with Claude Desktop!

## What This Does

This package provides:
1. **MCP Server** - Connects Claude Desktop to your Athena database
2. **Claude Skill** - Teaches Claude how to query TLC data effectively

Ask Claude questions like:
- "How many yellow taxi trips were there yesterday?"
- "What are the top 10 busiest pickup locations?"
- "Show me average fares by hour of day"
- "Compare yellow vs green taxi usage this month"

Claude will automatically convert your questions to SQL, execute them against Athena, and explain the results.

## Quick Start

### 1. Install Dependencies

```bash
cd scripts
conda env create -f environment.yml
```

### 2. Configure Environment

Set these environment variables (or add to `.env`):

```bash
export ATHENA_DATABASE="nyc_tlc"
export ATHENA_OUTPUT_LOCATION="s3://your-athena-results-bucket/query-results/"
export AWS_REGION="us-east-1"
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
```

### 3. Test the Server

```bash
cd scripts
python3 test_server.py
```

This will verify:
- ✓ Environment variables are set
- ✓ AWS credentials work
- ✓ Athena connection succeeds
- ✓ Tables are accessible

### 4. Configure Claude Desktop

Add to your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "nyc-tlc-athena": {
      "command": "python3",
      "args": [
        "/full/path/to/nyc-tlc-athena/scripts/mcp_server.py"
      ],
      "env": {
        "ATHENA_DATABASE": "nyc_tlc",
        "ATHENA_OUTPUT_LOCATION": "s3://your-athena-results-bucket/query-results/",
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "your-access-key",
        "AWS_SECRET_ACCESS_KEY": "your-secret-key"
      }
    }
  }
}
```

**Important**: Use the absolute path to `mcp_server.py`!

### 5. Install the Skill (Optional)

The skill teaches Claude best practices for querying TLC data. To install:

1. Package the skill:
   ```bash
   python3 /mnt/skills/examples/skill-creator/scripts/package_skill.py /path/to/nyc-tlc-athena
   ```

2. Upload the generated `.skill` file to Claude Desktop (Skills menu)

The skill helps Claude:
- Generate better SQL queries
- Format results clearly
- Handle edge cases
- Use appropriate date filters
- Join tables correctly

### 6. Restart Claude Desktop

After configuration, restart Claude Desktop to load the MCP server.

## Usage

Once configured, just ask Claude questions about your TLC data:

**Simple queries**:
> "How many trips yesterday?"

**Analytics**:
> "What's the average tip percentage by payment method?"

**Comparisons**:
> "Compare yellow taxi vs green taxi fares this week"

**Location analysis**:
> "Which neighborhoods have the highest trip counts?"

**Time patterns**:
> "Show me trips by hour for the last 7 days"

Claude will:
1. Understand your question
2. Check the database schema if needed
3. Generate appropriate SQL
4. Execute the query
5. Format and explain results

## Customization

### Update Table Schemas

Edit `scripts/mcp_server.py` and modify the `TABLE_SCHEMAS` dictionary to match your actual Athena tables:

```python
TABLE_SCHEMAS = {
    "your_table_name": {
        "description": "What this table contains",
        "columns": ["col1", "col2", "col3"]
    }
}
```

### Add Custom Query Patterns

Edit `references/sql_patterns.md` to add query patterns specific to your use case.

## Troubleshooting

### MCP Server Not Showing Up
- Check Claude Desktop logs (Help → Show Logs)
- Verify absolute path to `mcp_server.py`
- Ensure Python dependencies installed
- Check file permissions

### AWS Connection Errors
- Verify credentials with: `aws athena list-databases`
- Check IAM permissions (see `references/setup_guide.md`)
- Ensure S3 output bucket exists and is writable
- Verify region is correct

### Query Failures
- Run `python3 test_server.py` to diagnose
- Check table names match your Athena setup
- Review query syntax in Athena console
- Ensure date formats are correct

## Documentation

- `SKILL.md` - Claude skill documentation
- `references/setup_guide.md` - Detailed setup instructions
- `references/sql_patterns.md` - Common SQL query patterns
- `scripts/mcp_server.py` - Server implementation

## Architecture

```
User Question (Natural Language)
    ↓
Claude Desktop + Skill
    ↓
MCP Server (mcp_server.py)
    ↓
AWS Athena
    ↓
S3 Results
    ↓
Formatted Response to User
```

## Requirements

- Python 3.10+
- AWS account with Athena access
- Claude Desktop
- NYC TLC data loaded in Athena
- S3 bucket for query results

## License

MIT
