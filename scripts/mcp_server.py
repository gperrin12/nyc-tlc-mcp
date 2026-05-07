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
        "description": (
            "Taxi trip data (yellow and green taxis) with neighborhood-level geography. "
            "Uses pulocationid and dolocationid (~200 taxi zones); join to taxi_zones for geometry. "
            "No raw lat/lon—locations are aggregated to zone IDs."
        ),
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
    "par": {
        "description": (
            "Pre-2016 archived TLC trip data with raw pickup/dropoff coordinates. "
            "Has pickup_longitude, pickup_latitude, dropoff_longitude, dropoff_latitude. "
            "Column 'color' maps to 'type' in gtp_tlc_data (taxi type: yellow, green, etc.). "
            "Use for pre-2016 analysis and point-level geography; gtp_tlc_data is zone-level."
        ),
        "columns": [
            "vendorid", "lpep_pickup_datetime", "lpep_dropoff_datetime",
            "store_and_fwd_flag", "ratecodeid",
            "pickup_longitude", "pickup_latitude", "dropoff_longitude", "dropoff_latitude",
            "passenger_count", "trip_distance", "fare_amount", "extra",
            "mta_tax", "tip_amount", "tolls_amount", "ehail_fee",
            "improvement_surcharge", "total_amount", "payment_type",
            "trip_type", "tcolor", "year", "month", "color"
        ]
    },
    "taxi_zones": {
        "description": (
            "Taxi zone boundaries (263 zones across NYC). "
            "Join key: locationid (joins to gtp_tlc_data.pulocationid / dolocationid). "
            "Geometry stored as WKT in geometry_wkt — wrap with ST_GEOMETRY_FROM_TEXT() for spatial functions. "
            "Coordinates are WGS84 (lon/lat)."
        ),
        "columns": [
            "objectid", "shape_leng", "shape_area",
            "zone", "locationid", "borough",
            "geometry", "geometry_wkt"
        ]
    },
    "census_tracts": {
        "description": (
            "NYC census tracts (2020 Census, ~2,300 polygons), NYC DCP shoreline-clipped version. "
            "Join key: geoid (11-digit federal tract ID, joins to census_tract_demographics.geoid). "
            "Geometry stored as WKT in geometry_wkt — wrap with ST_GEOMETRY_FROM_TEXT() for spatial functions. "
            "Coordinates are WGS84 (lon/lat). "
            "Use for point-in-polygon joins from any lat/lon source (e.g. nypd_collisions, par): "
            "ST_CONTAINS(ST_GEOMETRY_FROM_TEXT(t.geometry_wkt), ST_POINT(CAST(longitude AS DOUBLE), CAST(latitude AS DOUBLE)))."
        ),
        "columns": [
            "boroct2020", "ct2020", "boroname", "borocode", "ctlabel",
            "nta2020", "ntaname", "cdta2020", "cdtaname",
            "geoid", "shape_leng", "shape_area", "geometry_wkt"
        ]
    },
    "census_tract_demographics": {
        "description": (
            "ACS 5-year demographic estimates per census tract for two non-overlapping vintages: "
            "_2018 suffix = 2014-2018 ACS, _2023 suffix = 2019-2023 ACS. "
            "Join key: geoid (joins to census_tracts.geoid). "
            "All values stored as STRING — use TRY_CAST(col AS BIGINT) or TRY_CAST(col AS DOUBLE) at query time. "
            "Census uses negative sentinels (~-666666666) for unavailable estimates; the loader nulls these out, "
            "but always wrap aggregations defensively (e.g. AVG(TRY_CAST(...)) ignores NULLs). "
            "Rates are NOT pre-computed: poverty rate = poverty_below / poverty_universe; "
            "% bachelor's+ = (edu_bachelors + edu_masters + edu_professional + edu_doctorate) / edu_universe_25plus; "
            "homeownership rate = housing_owner_occupied / housing_universe; "
            "% limited English households = (lang_lim_eng_spanish + lang_lim_eng_other_indo_european + "
            "lang_lim_eng_asian_pacific_island + lang_lim_eng_other) / lang_universe."
        ),
        "columns": [
            "geoid",
            # 2018 vintage
            "total_pop_2018", "median_age_2018",
            "median_household_income_2018", "poverty_universe_2018", "poverty_below_2018",
            "race_white_alone_2018", "race_black_alone_2018", "race_asian_alone_2018",
            "hispanic_or_latino_2018",
            "edu_universe_25plus_2018", "edu_bachelors_2018", "edu_masters_2018",
            "edu_professional_2018", "edu_doctorate_2018",
            "housing_universe_2018", "housing_owner_occupied_2018",
            "median_gross_rent_2018", "median_household_size_2018",
            "lang_universe_2018", "lang_lim_eng_spanish_2018",
            "lang_lim_eng_other_indo_european_2018", "lang_lim_eng_asian_pacific_island_2018",
            "lang_lim_eng_other_2018",
            # 2023 vintage
            "total_pop_2023", "median_age_2023",
            "median_household_income_2023", "poverty_universe_2023", "poverty_below_2023",
            "race_white_alone_2023", "race_black_alone_2023", "race_asian_alone_2023",
            "hispanic_or_latino_2023",
            "edu_universe_25plus_2023", "edu_bachelors_2023", "edu_masters_2023",
            "edu_professional_2023", "edu_doctorate_2023",
            "housing_universe_2023", "housing_owner_occupied_2023",
            "median_gross_rent_2023", "median_household_size_2023",
            "lang_universe_2023", "lang_lim_eng_spanish_2023",
            "lang_lim_eng_other_indo_european_2023", "lang_lim_eng_asian_pacific_island_2023",
            "lang_lim_eng_other_2023"
        ]
    },
    "nypd_collisions": {
        "description": (
            "NYPD Motor Vehicle Collisions (~2M rows, 2012-present). "
            "Partitioned by year (STRING) and month (STRING, zero-padded). "
            "Has raw lat/lon — use ST_POINT(CAST(longitude AS DOUBLE), CAST(latitude AS DOUBLE)) "
            "for spatial joins to taxi_zones or census_tracts via ST_CONTAINS. "
            "Filter out NULL/zero coordinates and bound to NYC: "
            "latitude BETWEEN 40.4 AND 41.0 AND longitude BETWEEN -74.3 AND -73.6. "
            "Casualty columns (number_of_persons_injured, number_of_persons_killed, etc.) are STRING — "
            "use TRY_CAST(... AS INTEGER). "
            "Always filter by partition (year, month) for cost efficiency."
        ),
        "columns": [
            "collision_id", "crash_date", "crash_time",
            "borough", "zip_code",
            "latitude", "longitude", "location_latitude", "location_longitude",
            "on_street_name", "cross_street_name", "off_street_name",
            "number_of_persons_injured", "number_of_persons_killed",
            "number_of_pedestrians_injured", "number_of_pedestrians_killed",
            "number_of_cyclist_injured", "number_of_cyclist_killed",
            "number_of_motorist_injured", "number_of_motorist_killed",
            "contributing_factor_vehicle_1", "contributing_factor_vehicle_2",
            "contributing_factor_vehicle_3", "contributing_factor_vehicle_4",
            "contributing_factor_vehicle_5",
            "vehicle_type_code1", "vehicle_type_code2",
            "vehicle_type_code_3", "vehicle_type_code_4", "vehicle_type_code_5",
            "year", "month"
        ]
    },
    "nyc_311": {
        "description": (
            "NYC 311 Service Requests (2020-present, ~40M+ rows). "
            "Partitioned by year (STRING) and month (STRING, zero-padded) — "
            "ALWAYS filter by year/month partition to avoid full-table scans. "
            "All columns are STRING; cast at query time with TRY_CAST. "
            "Date columns (created_date, closed_date, due_date, resolution_action_updated_date) "
            "are ISO-8601 strings — parse with FROM_ISO8601_TIMESTAMP() or DATE_PARSE() as needed. "
            "Borough column is populated natively ('BROOKLYN', 'MANHATTAN', 'QUEENS', 'BRONX', "
            "'STATEN ISLAND', or 'Unspecified') — no spatial join needed for borough-level analysis. "
            "Has raw lat/lon for finer geography: ST_POINT(CAST(longitude AS DOUBLE), CAST(latitude AS DOUBLE)) "
            "joins to census_tracts.geometry_wkt or taxi_zones.geometry_wkt via ST_CONTAINS. "
            "Filter NYC bounds: latitude BETWEEN 40.4 AND 41.0 AND longitude BETWEEN -74.3 AND -73.6. "
            "Key categorical columns: complaint_type (e.g. 'Noise - Residential', 'Illegal Parking'), "
            "agency (NYPD, DSNY, DOT, HPD, etc.), status (Open, Closed, In Progress), "
            "open_data_channel_type (PHONE, ONLINE, MOBILE). "
            "Resolution time = closed_date - created_date; many requests have NULL closed_date if still open."
        ),
        "columns": [
            "unique_key", "created_date", "closed_date",
            "agency", "agency_name",
            "complaint_type", "descriptor", "location_type",
            "incident_zip", "incident_address", "street_name",
            "cross_street_1", "cross_street_2",
            "intersection_street_1", "intersection_street_2",
            "address_type", "city", "landmark", "facility_type",
            "status", "due_date", "resolution_description",
            "resolution_action_updated_date",
            "community_board", "bbl", "borough",
            "x_coordinate_state_plane", "y_coordinate_state_plane",
            "open_data_channel_type",
            "park_facility_name", "park_borough",
            "vehicle_type", "taxi_company_borough", "taxi_pick_up_location",
            "bridge_highway_name", "bridge_highway_direction",
            "road_ramp", "bridge_highway_segment",
            "latitude", "longitude", "location_latitude", "location_longitude",
            "year", "month"
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
    schema_text = "NYC Civic Data Schema (taxi trips, zones, census tracts, demographics, collisions):\n\n"
    
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
                "Execute a SQL query against NYC civic data in Athena. "
                "Accepts natural language questions or direct SQL queries. "
                "The tool will help convert natural language to SQL if needed. "
                "Available tables: "
                "gtp_tlc_data (taxi trips, zone-level via pulocationid/dolocationid), "
                "par (pre-2016 taxi trips with raw lat/lon), "
                "taxi_zones (263 zones, geometry as WKT), "
                "census_tracts (~2,300 NYC tracts, geometry as WKT, joins to demographics on geoid), "
                "census_tract_demographics (ACS 5-year demographics, two vintages: _2018 and _2023), "
                "nypd_collisions (~2M crash records with raw lat/lon, partitioned by year/month), "
                "nyc_311 (~40M+ service requests 2020-present with lat/lon and borough, partitioned by year/month). "
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
                "Get the schema information for all tables in the Athena database "
                "(taxi trips, taxi zones, census tracts, ACS demographics, NYPD collisions, 311 service requests). "
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
                "Generate a SQL query from a natural language question about NYC civic data "
                "(taxi trips, census tracts, demographics, traffic collisions, 311 service requests). "
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