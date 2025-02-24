import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from .pdf_extractor import ExtractedContent

@dataclass
class JournalMetadata:
    """Journal-specific metadata required by PubMed (simplified)."""
    journal_id: str
    journal_title: str
    issn: Optional[str] = None
    publisher: Optional[str] = None

@dataclass
class AuthorMetadata:
    """Structured author information."""
    surname: str
    given_names: str
    credentials: Optional[str] = None
    email: Optional[str] = None
    affiliations: List[str] = field(default_factory=list)

@dataclass
class ArticleMetadata:
    """Extended article metadata for PubMed requirements."""
    article_type: str
    article_id: Optional[str] = None
    title: str = "Untitled"
    authors: List[AuthorMetadata] = field(default_factory=list)
    corresponding_author: Optional[str] = None
    abstract: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    publication_date: Dict[str, str] = field(default_factory=dict)
    volume: Optional[str] = None
    issue: Optional[str] = None
    fpage: Optional[str] = None
    lpage: Optional[str] = None
    doi: Optional[str] = None
    funding_statement: Optional[str] = None
    conflict_statement: Optional[str] = None

class MetadataExtractor:
    """
    Metadata extractor that primarily uses GROBID-extracted metadata
    but can fall back to regex-based approaches when needed.
    """

    def __init__(self, default_article_type: str = "research-article"):
        """
        Args:
            default_article_type: Default article type if none is detected or provided by user.
        """
        self.default_article_type = default_article_type
        self._setup_logging()

    def _setup_logging(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            self.logger.addHandler(handler)

    def extract_metadata(
        self, 
        extracted_content: ExtractedContent,
        user_article_type: Optional[str] = None
    ) -> Tuple[JournalMetadata, ArticleMetadata]:
        """
        Main method to extract both JournalMetadata and ArticleMetadata.
        Primarily uses pre-extracted GROBID data from ExtractedContent.

        Args:
            extracted_content: The result of PDFExtractor (with GROBID data).
            user_article_type: If the user selected "abstract" or "full article" from the UI,
                               you can override the default here.

        Returns:
            (journal_meta, article_meta) as a tuple of dataclass instances.
        """
        self.logger.info("Starting metadata extraction from GROBID data.")
        
        # 1. Journal metadata from GROBID
        journal_meta = self._extract_journal_metadata(extracted_content)

        # 2. Article metadata from GROBID
        article_meta = self._extract_article_metadata(extracted_content, user_article_type)

        self.logger.info("Metadata extraction complete.")
        return journal_meta, article_meta

    def _extract_journal_metadata(self, content: ExtractedContent) -> JournalMetadata:
        """
        Extract JournalMetadata from GROBID-parsed content.
        Fallback to regex methods if needed.
        """
        # Use GROBID-extracted journal metadata if available
        if content.journal_metadata:
            journal_title = content.journal_metadata.get('journal_title', "Unknown Journal")
            issn = content.journal_metadata.get('issn')
            publisher = content.journal_metadata.get('publisher')
            
            # Generate journal ID from title
            journal_id = self._generate_journal_id(journal_title)
            
            return JournalMetadata(
                journal_id=journal_id,
                journal_title=journal_title,
                issn=issn,
                publisher=publisher
            )
            
        # Fallback to regex methods if GROBID didn't extract journal metadata
        raw_text = content.raw_text or ""
        chunk = raw_text[:300]  # Look only at the beginning

        issn = self._find_issn(chunk)
        journal_title = self._find_journal_title(chunk)
        journal_id = self._generate_journal_id(journal_title)

        # If you need a publisher, you can do a naive search for "Publisher: X"
        publisher_match = re.search(r'Publisher:\s*(.+)', chunk)
        publisher = publisher_match.group(1).strip() if publisher_match else None

        return JournalMetadata(
            journal_id=journal_id,
            journal_title=journal_title,
            issn=issn,
            publisher=publisher
        )

    def _extract_article_metadata(
        self, 
        content: ExtractedContent, 
        user_article_type: Optional[str]
    ) -> ArticleMetadata:
        """
        Extract ArticleMetadata from GROBID-parsed content.
        Fallback to regex methods if needed.
        """
        # 1. Article type (use user input if available, else default)
        article_type = user_article_type or self.default_article_type

        # 2. Title - use GROBID-extracted title if available
        title = content.title or "Untitled Article"

        # 3. Authors - convert GROBID authors to AuthorMetadata
        authors = []
        for author_data in content.authors:
            affiliations = author_data.get('affiliations', [])
            email = author_data.get('email')
            
            author = AuthorMetadata(
                surname=author_data.get('surname', ''),
                given_names=author_data.get('given_names', ''),
                email=email,
                affiliations=affiliations
            )
            authors.append(author)
            
            # Set corresponding author if marked as such
            if author_data.get('is_corresponding', False) and email:
                corresponding_author = f"{author.given_names} {author.surname} ({email})"
            elif not corresponding_author and author_data.get('is_corresponding', False):
                corresponding_author = f"{author.given_names} {author.surname}"

        # 4. Abstract - use GROBID-extracted abstract
        abstract = content.abstract
            
        # 5. Publication info from GROBID journal metadata
        volume = content.journal_metadata.get('volume')
        issue = content.journal_metadata.get('issue')
        fpage = content.journal_metadata.get('fpage')
        lpage = content.journal_metadata.get('lpage')
        
        # 6. Publication date - try to find in GROBID metadata or fall back to regex
        pub_date = self._find_publication_date(content.raw_text)
        
        # 7. DOI - try to find in GROBID metadata or fall back to regex
        doi = self._find_doi(content.raw_text)
        
        # 8. Keywords - try to find in text since GROBID doesn't always extract keywords
        keywords = self._find_keywords(content.raw_text)

        return ArticleMetadata(
            article_type=article_type,
            title=title,
            authors=authors,
            corresponding_author=corresponding_author if 'corresponding_author' in locals() else None,
            abstract=abstract,
            keywords=keywords,
            publication_date=pub_date,
            volume=volume,
            issue=issue,
            fpage=fpage,
            lpage=lpage,
            doi=doi
        )

    # ----------------------------------------------------------------------
    # Fallback methods for when GROBID data is insufficient
    # ----------------------------------------------------------------------

    def _generate_journal_id(self, title: str) -> str:
        """Simple ID from journal title."""
        words = title.split()
        # e.g. "Journal of Biology" => "JOB"
        letters = [w[0].upper() for w in words if w and w[0].isalpha()]
        return "".join(letters) if letters else "UNKNOWN"

    def _find_issn(self, text: str) -> Optional[str]:
        """Regex search for an ISSN pattern."""
        match = re.search(r'ISSN[:\s]*(\d{4}-\d{4})', text, re.IGNORECASE)
        return match.group(1) if match else None

    def _find_journal_title(self, text: str) -> str:
        """
        Look for something like "Journal of X", "Annals of X", etc.
        Fallback: "Unknown Journal"
        """
        pattern = re.compile(r'(Journal|Annals|Archives|International Journal|British Journal|American Journal|BMC)\s+of\s+[A-Z][A-Za-z\s]+')
        match = pattern.search(text)
        if match:
            return match.group(0).strip()
        return "Unknown Journal"

    def _find_keywords(self, text: str) -> List[str]:
        """
        Look for a line starting with "Keywords:" or "Key words:" and parse comma/semicolon.
        """
        pattern = re.compile(r'(Key\s*words?|Keywords?)[:\-]+\s*(.+?)(?:\n\n|\n[A-Z]|\.\s+[A-Z])', re.IGNORECASE | re.DOTALL)
        match = pattern.search(text)
        if match:
            keywords_str = match.group(2).strip()
            # Split on commas or semicolons
            parts = re.split(r'[;,]', keywords_str)
            return [p.strip() for p in parts if p.strip()]
        return []

    def _find_publication_date(self, text: str) -> Dict[str, str]:
        """
        Look for publication date patterns in text.
        Return a dict with {"year": "...", "month": "...", "day": "..."}
        """
        pubdate = {}

        # Try "YYYY-MM-DD"
        match_iso = re.search(r'(?:Published|Received|Accepted)[:\s]+(\d{4})-(\d{2})-(\d{2})', text)
        if match_iso:
            pubdate["year"] = match_iso.group(1)
            pubdate["month"] = match_iso.group(2)
            pubdate["day"] = match_iso.group(3)
            return pubdate

        # Try "Published on Month DD, YYYY"
        match_long = re.search(r'(?:Published|Received|Accepted)\s+(?:on\s+)?([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', text)
        if match_long:
            pubdate["year"] = match_long.group(3)
            pubdate["month"] = match_long.group(1)  # e.g. "January"
            pubdate["day"] = match_long.group(2)
            return pubdate
            
        # Just try to find a year
        year_match = re.search(r'©\s*(\d{4})|(?:19|20)(\d{2})[^\d]', text)
        if year_match:
            year = year_match.group(1) or year_match.group(2)
            if year and len(year) == 2:  # Handle 2-digit year
                prefix = '19' if int(year) > 50 else '20'  # Heuristic: 50+ is 1900s, else 2000s
                year = prefix + year
            pubdate["year"] = year
            
        return pubdate

    def _find_doi(self, text: str) -> Optional[str]:
        """
        Look for DOI pattern in text.
        """
        # Match DOI in various formats
        doi_pattern = re.compile(r'(?:doi|DOI)[:\s]*(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)')
        doi_match = doi_pattern.search(text)
        
        if doi_match:
            return doi_match.group(1)
            
        # Try alternative pattern (just the DOI itself)
        alt_doi_match = re.search(r'(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)', text)
        if alt_doi_match:
            return alt_doi_match.group(1)
            
        return None