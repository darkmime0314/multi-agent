import os
import re
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:admin123@my-postgres-postgresql.database.svc.cluster.local:5432/postgres",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class FilterRuleModel(Base):
    __tablename__ = "filter_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    pattern = Column(String, nullable=False)


Base.metadata.create_all(engine)


class InputFilter:
    """Utility class to check if a given text contains sensitive information."""

    _compiled_rules = []

    @classmethod
    def load_rules(cls) -> None:
        """Load filter rules from the database and compile regex patterns."""
        with SessionLocal() as session:
            rules = session.query(FilterRuleModel).all()
            cls._compiled_rules = [re.compile(r.pattern, re.IGNORECASE) for r in rules]

    @classmethod
    def contains_sensitive(cls, text: str) -> bool:
        """Return True if the text matches any filter rule."""
        if not cls._compiled_rules:
            cls.load_rules()
        return any(p.search(text) for p in cls._compiled_rules)

