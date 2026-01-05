#!/usr/bin/env python3
"""
NYC TLC Athena MCP Server

This MCP server provides natural language querying capabilities for NYC TLC data stored in AWS Athena.
It converts natural language queries into SQL and executes them against your Athena tables.
"""

import asyncio
import json
import os
import sys
from typing import Any, Sequence
import boto3
import time

# Add MCP SDK to path if needed
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
except ImportError:
    print("Error: MCP SDK not installed. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Configuration
DATABASE_NAME = os.getenv("ATHENA_DATABASE", "nyc_tlc")
S3_OUTPUT_LOCATION = os.getenv("ATHENA_OUTPUT_LOCATION", "s3://your-bucket/athena-results/")
REGION = os.getenv("AWS_REGION", "us-east-1")

# Initialize Athena client
athena_client = boto3.client('athena', region_name=REGION)

# Table schema information (customize based on your actual schema)
TABLE_SCHEMAS = {
    "gtp_tlc_data": {
        "description": "Taxi trip data (right now just yellow and green taxis), including pickup/dropoff locations, times, fares, and passenger counts",
        "columns": [
            "vendorid", "tpep_pickup_datetime", "tpep_dropoff_datetime",
            "passenger_count", "trip_distance", "ratecodeid",
            "store_and_fwd_flag", "pulocationid", "dolocationid",
            "payment_type", "fare_amount", "extra", "mta_tax",
            "tip_amount", "tolls_amount", "improvement_surcharge",
            "total_amount", "congestion_surcharge", "airport_fee",
            "type", "year", "month"
        ]
    },
    "taxi_zones": {
        "description": "Taxi zone boundaries for location lookups and joins (includes geometry and WKT)",
        "columns": [
            "objectid", "shape_leng", "shape_area",
            "zone", "locationid", "borough",
            "geometry", "geometry_wkt"
        ]
    },
}


def execute_athena_query(query: str, max_wait_seconds: int = 60) -> dict:
    """Execute an Athena query and return results"""
    try:
        # Start query execution
        response = athena_client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': DATABASE_NAME},
            ResultConfiguration={'OutputLocation': S3_OUTPUT_LOCATION}
        )
        
        query_execution_id = response['QueryExecutionId']
        
        # Wait for query to complete
        elapsed = 0
        while elapsed < max_wait_seconds:
            status_response = athena_client.get_query_execution(
                QueryExecutionId=query_execution_id
            )
            status = status_response['QueryExecution']['Status']['State']
            
            if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                break
            
            time.sleep(1)
            elapsed += 1
        
        if status != 'SUCCEEDED':
            error_msg = status_response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
            return {
                "success": False,
                "error": f"Query {status.lower()}: {error_msg}",
                "query": query
            }
        
        # Get query results
        results = athena_client.get_query_results(
            QueryExecutionId=query_execution_id,
            MaxResults=100  # Limit for safety
        )
        
        # Parse results
        columns = [col['Label'] for col in results['ResultSet']['ResultSetMetadata']['ColumnInfo']]
        rows = []
        
        for row in results['ResultSet']['Rows'][1:]:  # Skip header row
            row_data = [field.get('VarCharValue', '') for field in row['Data']]
            rows.append(dict(zip(columns, row_data)))
        
        return {
            "success": True,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "query": query
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "query": query
        }


def get_schema_info() -> str:
    """Return formatted schema information for all tables"""
    schema_text = "NYC TLC Database Schema:\n\n"
    
    for table_name, info in TABLE_SCHEMAS.items():
        schema_text += f"Table: {table_name}\n"
        schema_text += f"Description: {info['description']}\n"
        schema_text += f"Columns: {', '.join(info['columns'])}\n\n"
    
    return schema_text


app = Server("nyc-tlc-athena")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools"""
    return [
        Tool(
            name="query_tlc_data",
            description=(
                "Execute a SQL query against NYC TLC data in Athena. "
                "Accepts natural language questions or direct SQL queries. "
                "The tool will help convert natural language to SQL if needed. "
                "Available tables: gtp_tlc_data, taxi_zones. "
                "Returns up to 100 rows of results."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Either a SQL query or a natural language question about the TLC data"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_schema",
            description=(
                "Get the schema information for all NYC TLC tables in the Athena database. "
                "Returns table names, descriptions, and column lists."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="generate_sql",
            description=(
                "Generate a SQL query from a natural language question about NYC TLC data. "
                "Returns the SQL without executing it, allowing you to review before running."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural language question about the TLC data"
                    }
                },
                "required": ["question"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent]:
    """Handle tool calls"""
    
    if name == "get_schema":
        schema_info = get_schema_info()
        return [TextContent(type="text", text=schema_info)]
    
    elif name == "generate_sql":
        question = arguments.get("question", "")
        
        response = {
            "question": question,
            "note": "Use Claude's natural language understanding to generate SQL based on the question and schema",
            "schema": get_schema_info()
        }
        
        return [TextContent(
            type="text",
            text=f"Question: {question}\n\n{get_schema_info()}\n\nGenerate appropriate SQL for this question."
        )]
    
    elif name == "query_tlc_data":
        query_input = arguments.get("query", "")
        
        # Check if it looks like SQL or natural language
        query_lower = query_input.lower().strip()
        is_sql = query_lower.startswith(('select', 'with', 'show', 'describe'))
        
        if not is_sql:
            # Return schema to help Claude generate SQL
            return [TextContent(
                type="text",
                text=(
                    f"Natural language query detected: '{query_input}'\n\n"
                    "Please generate SQL based on this question and the schema below:\n\n"
                    f"{get_schema_info()}\n\n"
                    "Then call query_tlc_data again with the generated SQL."
                )
            )]
        
        # Execute the SQL query
        result = execute_athena_query(query_input)
        
        if result["success"]:
            output = f"Query executed successfully!\n\n"
            output += f"SQL: {result['query']}\n\n"
            output += f"Returned {result['row_count']} rows\n\n"
            
            if result['row_count'] > 0:
                output += "Results:\n"
                output += json.dumps(result['rows'], indent=2)
            else:
                output += "No results returned."
        else:
            output = f"Query failed!\n\n"
            output += f"SQL: {result['query']}\n\n"
            output += f"Error: {result['error']}"
        
        return [TextContent(type="text", text=output)]
    
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
