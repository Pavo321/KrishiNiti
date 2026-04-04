import { Pool } from "pg";

const pool = new Pool({
  connectionString:
    process.env.DATABASE_URL ||
    "postgresql://krishiniti_app:krishiniti_dev_password_2026@localhost:5432/krishiniti",
});

export default pool;
