import sqlalchemy as sa
import traceback

# --- CONFIGURATION ---
# Paths to your database files
OLD_DB_URI = 'sqlite:///instance/old_app.db'
NEW_DB_URI = 'sqlite:///instance/app.db'

# --- DATABASE CONNECTION SETUP ---
old_engine = sa.create_engine(OLD_DB_URI)
new_engine = sa.create_engine(NEW_DB_URI)

old_meta = sa.MetaData()
new_meta = sa.MetaData()

print("INFO: Connecting to databases...")


def migrate_table(table_name, old_conn, new_conn):
    """
    Generic function to migrate data from a table in the old DB to the new DB.
    It automatically handles missing columns in the source.
    """
    print(f"\n--- Migrating table '{table_name}' ---")
    try:
        # Reflect table structure from both databases
        old_table = sa.Table(table_name, old_meta, autoload_with=old_conn)
        new_table = sa.Table(table_name, new_meta, autoload_with=new_conn)

        # Get column names from the new table to filter data
        new_columns = {c.name for c in new_table.columns}

        # Read all data from the old table
        old_data = old_conn.execute(sa.select(old_table)).fetchall()
        print(f"INFO: Found {len(old_data)} records in source table '{table_name}'.")

        if not old_data:
            print(f"SUCCESS: No data to migrate for '{table_name}'.")
            return

        # Prepare data for insertion into the new table
        cleaned_data = []
        for row in old_data:
            row_dict = dict(row._mapping)
            # Keep only the data for columns that exist in the new table
            filtered_row = {key: value for key, value in row_dict.items() if key in new_columns}
            cleaned_data.append(filtered_row)

        if cleaned_data:
            # Insert the cleaned data into the new table
            new_conn.execute(new_table.insert(), cleaned_data)
            print(f"SUCCESS: Data for '{table_name}' has been migrated.")

    except sa.exc.NoSuchTableError:
        print(f"WARNING: Table '{table_name}' not found in the old database. Skipping.")
    except Exception as e:
        # Re-raise the exception to be caught by the main handler
        print(f"ERROR: Failed to migrate table '{table_name}'.")
        raise e


# --- MAIN MIGRATION PROCESS ---
try:
    with old_engine.connect() as old_conn, new_engine.connect() as new_conn:
        print("INFO: Database connections established.")

        # The order of migration is important to respect foreign key constraints.
        # Start with tables that do not depend on others.
        TABLES_TO_MIGRATE = [
            'users',
            'defect_types',
            'application_types',
            'responsible_persons',
            'applications',
            'defects',
            'application_logs',
            'responsible_assignments',  # The many-to-many mapping table
            'email_logs'
        ]

        # Begin a transaction in the new database
        with new_conn.begin():
            print("\nINFO: Starting migration transaction.")

            for table in TABLES_TO_MIGRATE:
                migrate_table(table, old_conn, new_conn)

        print("\nSUCCESS: Migration transaction committed successfully.")

except Exception as e:
    print(f"\nCRITICAL: An error occurred during the migration: {e}")
    print("--- FULL ERROR TRACEBACK ---")
    traceback.print_exc()
    print("----------------------------")
    print("\nCRITICAL: The transaction was rolled back. No data was changed in the new database.")

finally:
    print("\nINFO: Migration script has finished.")