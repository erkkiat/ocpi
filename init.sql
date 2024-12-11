DO
$$
BEGIN
    -- Create the role only if it does not already exist
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ocpi') THEN
        CREATE ROLE ocpi WITH LOGIN PASSWORD 'ocpiocpi';
    END IF;

    -- Create the database only if it does not already exist
    IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'ocpi') THEN
        CREATE DATABASE ocpi OWNER ocpi;
    END IF;
END
$$;
