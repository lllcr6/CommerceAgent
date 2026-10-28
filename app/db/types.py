"""ID storage matching the SQL migrations, with SQLite autoincrement support."""
from sqlalchemy import BigInteger, Integer
from sqlalchemy.dialects.mysql import BIGINT

# The original SQL migrations use BIGINT UNSIGNED for IDs and references.
# MySQL requires the FK and referenced columns to have the same signedness.
BIGINT_ID = (BigInteger()
             .with_variant(BIGINT(unsigned=True), "mysql", "mariadb")
             .with_variant(Integer(), "sqlite"))
