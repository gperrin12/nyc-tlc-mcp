#!/usr/bin/env python3
"""
Test script for NYC TLC Athena MCP Server

This script tests the MCP server functionality without requiring Claude Desktop.
Run this to verify your AWS configuration and table access.
"""

import os
import sys
import json

# Add parent directory to path to import the server
sys.path.insert(0, os.path.dirname(__file__))

try:
    from mcp_server import execute_athena_query, get_schema_info, TABLE_SCHEMAS
except ImportError as e:
    print(f"Error importing server: {e}")
    print("Make sure you're running this from the scripts directory")
    sys.exit(1)


def test_configuration():
    """Test that all required configuration is present"""
    print("=" * 60)
    print("Testing Configuration")
    print("=" * 60)
    
    required_vars = {
        "ATHENA_DATABASE": os.getenv("ATHENA_DATABASE"),
        "ATHENA_OUTPUT_LOCATION": os.getenv("ATHENA_OUTPUT_LOCATION"),
        "AWS_REGION": os.getenv("AWS_REGION")
    }
    
    all_present = True
    for var, value in required_vars.items():
        status = "✓" if value else "✗"
        print(f"{status} {var}: {value or 'NOT SET'}")
        if not value:
            all_present = False
    
    if not all_present:
        print("\n⚠️  Some required environment variables are missing!")
        print("Set them in your environment or .env file")
        return False
    
    print("\n✓ All required configuration present")
    return True


def test_schema():
    """Test schema retrieval"""
    print("\n" + "=" * 60)
    print("Testing Schema Retrieval")
    print("=" * 60)
    
    schema = get_schema_info()
    print(schema)
    
    print(f"\n✓ Schema loaded for {len(TABLE_SCHEMAS)} tables")
    return True


def test_simple_query():
    """Test a simple query that should work on any database"""
    print("\n" + "=" * 60)
    print("Testing Simple Query")
    print("=" * 60)
    
    database = os.getenv("ATHENA_DATABASE", "nyc_tlc")
    query = f"SHOW TABLES IN {database}"
    
    print(f"Query: {query}")
    print("\nExecuting...")
    
    result = execute_athena_query(query, max_wait_seconds=30)
    
    if result["success"]:
        print("\n✓ Query executed successfully!")
        print(f"Found {result['row_count']} tables:")
        for row in result["rows"]:
            print(f"  - {row.get('tab_name', list(row.values())[0])}")
        return True
    else:
        print("\n✗ Query failed!")
        print(f"Error: {result['error']}")
        return False


def test_table_query():
    """Test querying a specific table"""
    print("\n" + "=" * 60)
    print("Testing Table Query")
    print("=" * 60)
    
    # Try to find a table to query
    table_name = None
    for table in TABLE_SCHEMAS.keys():
        table_name = table
        break
    
    if not table_name:
        print("No tables configured in TABLE_SCHEMAS")
        return False
    
    query = f"SELECT * FROM {table_name} LIMIT 5"
    
    print(f"Query: {query}")
    print("\nExecuting...")
    
    result = execute_athena_query(query, max_wait_seconds=30)
    
    if result["success"]:
        print("\n✓ Query executed successfully!")
        print(f"Columns: {', '.join(result['columns'])}")
        print(f"Returned {result['row_count']} rows")
        
        if result['row_count'] > 0:
            print("\nSample data:")
            print(json.dumps(result['rows'][0], indent=2))
        return True
    else:
        print("\n✗ Query failed!")
        print(f"Error: {result['error']}")
        print("\nThis might mean:")
        print("  - The table doesn't exist in your database")
        print("  - You need to update TABLE_SCHEMAS in mcp_server.py")
        print("  - There's a permissions issue")
        return False


def main():
    """Run all tests"""
    print("\n🧪 NYC TLC Athena MCP Server Tests\n")
    
    tests = [
        ("Configuration", test_configuration),
        ("Schema", test_schema),
        ("Simple Query", test_simple_query),
        ("Table Query", test_table_query)
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} test crashed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Your MCP server is ready to use.")
        print("\nNext steps:")
        print("1. Add the server to Claude Desktop config")
        print("2. Restart Claude Desktop")
        print("3. Ask Claude to query your TLC data!")
    else:
        print("\n⚠️  Some tests failed. Review the errors above.")
        print("\nCommon issues:")
        print("- AWS credentials not configured")
        print("- Database/table names don't match your setup")
        print("- S3 output location doesn't exist or isn't writable")
        print("- IAM permissions missing")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
