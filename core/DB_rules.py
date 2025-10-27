rules = {
  "PostgreSQL": {
    "Case Sensitivity": "Unquoted identifiers are folded to lowercase. Use double quotes for case-sensitive identifiers.",
    "Schema Handling": "The default schema is public. Specify the schema if accessing objects outside public.",
    "Quoting Identifiers": "Use double quotes for identifiers with mixed or uppercase letters.",
    "Reserved Words": "Avoid using reserved keywords as identifiers unless they are quoted.",
    "Additional Info": """Double-Check Identifiers: Ensure that the chatbot explicitly uses double quotes for identifiers with uppercase or mixed-case letters, like "Occupancy", "CreatedDate", and "Occupied".
                          Enforce Case Sensitivity: If you want to enforce case sensitivity, always quote table names and columns, e.g., "Occupancy" instead of Occupancy.
                          Default to Lowercase: If your table and column names are all lowercase in the database, make sure the chatbot consistently generates unquoted, lowercase identifiers.
                          Provide Context: Ensure that the chatbot is aware of the schema and specific database configuration. If your table is not in the public schema, the chatbot should include the schema name, e.g., "myschema"."Occupancy"."""
  },
  "MySQL": {
    "Case Sensitivity": "Table names are case-sensitive on Unix-based systems but not on Windows. Column names are not case-sensitive.",
    "Schema Handling": "MySQL uses the term 'database' instead of 'schema.' Specify the database name if accessing objects outside the current database.",
    "Quoting Identifiers": "Use backticks (`) for identifiers with spaces or reserved words.",
    "Auto-Increment": "Primary key columns can be auto-incremented using the AUTO_INCREMENT attribute."
  },
  "SQL Server": {
    "Case Sensitivity": "SQL Server is case-insensitive by default. However, ensure that the collation settings of your database are set to case-insensitive, unless explicitly using a case-sensitive collation.",
    "Schema Handling": "Always ensure the correct schema is used in your queries. Use the format [schema_name].[table_name] for schema-qualified queries. Verify that both the schema and table exist in the database before querying.",
    "Quoting Identifiers": "Use square brackets [] around identifiers only if they contain special characters, spaces, or reserved keywords. Do not use square brackets unnecessarily.",
    "Transactions": "SQL Server supports explicit transaction handling using BEGIN TRANSACTION, COMMIT, and ROLLBACK. Ensure proper transaction management in your queries to avoid data inconsistencies.",
    "Additional Information": "DO NOT USE IT If 'schema_name' is not given specifically. \n Ensure that the columns you are aggregating with `SUM` are of a numeric data type. "
  },
  "Oracle": {
    "Case Sensitivity": "Unquoted identifiers are folded to uppercase. Use double quotes for case-sensitive identifiers.",
    "Schema Handling": "Each user has a default schema matching their username. Prefix with the schema name if accessing objects outside the default schema.",
    "Quoting Identifiers": "Use double quotes for identifiers with mixed case or special characters.",
    "Reserved Words": "Avoid using reserved keywords as identifiers unless quoted."
  },
  "SQLite": {
    "Case Sensitivity": "SQLite is case-insensitive for most identifiers by default, but case sensitivity can be enforced with double quotes.",
    "Schema Handling": "SQLite does not use schemas like other RDBMS. It operates on a single file, so there's no need to specify a schema.",
    "Quoting Identifiers": "Double quotes can be used, but are not often necessary.",
    "Transactions": "SQLite supports transactions using BEGIN TRANSACTION, COMMIT, and ROLLBACK."
  },
  "MariaDB": {
    "Case Sensitivity": "Follows similar case sensitivity rules as MySQL. Table names are case-sensitive on Unix-based systems.",
    "Schema Handling": "Like MySQL, MariaDB uses 'database' instead of 'schema.' Use database_name.table_name.",
    "Quoting Identifiers": "Use backticks (`) for identifiers with spaces or reserved words.",
    "Character Sets and Collations": "Supports a wide range of character sets and collations that can be set at the database, table, or column level."
  },
  "IBM Db2": {
    "Case Sensitivity": "Unquoted identifiers are folded to uppercase. Use double quotes for case-sensitive identifiers.",
    "Schema Handling": "Use  <schema_name.table_name> format to specify the schema.",
    "Quoting Identifiers": "Use double quotes for case-sensitive or special character identifiers.",
    "Tablespaces": "Db2 uses tablespaces to manage physical storage of database objects."
  },
  "Cassandra": {
    "Case Sensitivity": "Identifiers are case-insensitive unless quoted.",
    "Schema Handling": "Cassandra uses 'keyspaces' instead of schemas. Specify the keyspace if accessing objects outside the current keyspace.",
    "Quoting Identifiers": "Use double quotes for case-sensitive identifiers.",
    "Partitioning": "Data is partitioned across nodes using a partition key, which should be chosen carefully to distribute data evenly."
  },
  "MongoDB": {
    "Case Sensitivity": "Collection names are case-sensitive.",
    "Schema Handling": "MongoDB uses databases, but collections do not have schemas. Collections within a database are unique.",
    "Quoting Identifiers": "Quoting is not applicable as MongoDB uses JSON-like documents.",
    "Indexing": "Ensure proper indexing of fields to optimize query performance."
  },
  "Amazon Redshift": {
    "Case Sensitivity": "Follows PostgreSQL conventions; unquoted identifiers are folded to lowercase.",
    "Schema Handling": "Redshift uses schemas like PostgreSQL. Specify the schema with  <schema_name.table_name> format.",
    "Quoting Identifiers": "Use double quotes for case-sensitive or special character identifiers.",
    "Distribution Style": "Choose an appropriate distribution style (KEY, EVEN, or ALL) for tables to optimize performance."
  },
  "Google BigQuery": {
    "Case Sensitivity": "Identifiers are case-insensitive unless quoted with backticks (`).",
    "Schema Handling": "BigQuery uses datasets instead of schemas. Specify the dataset with dataset_name.table_name.",
    "Quoting Identifiers": "Use backticks for identifiers with special characters or to preserve case.",
    "Partitioning": "Use partitioned tables for managing large datasets efficiently."
  }
}
