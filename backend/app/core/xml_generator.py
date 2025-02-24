import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from lxml import etree

from dataclasses import asdict
from .metadata_extractor import JournalMetadata, ArticleMetadata, AuthorMetadata
from .text_processor import ProcessedContent, ProcessedSection, ReferenceData

class XMLGeneratorConfig:
    """Configuration for XML generation, including DTD and entity file management."""
    
    # Required DTD files
    REQUIRED_DTD_FILES = [
        'journalpublishing.dtd',
        'annotation.ent',
        'articlemeta.ent',
        'backmatter.ent',
        'catalog.ent',
        'common.ent',
        'modules.ent'
    ]

    # Journal metadata constants - these will always be used for JCAD
    JOURNAL_METADATA = {
        'id': 'JCAD',
        'title': 'The Journal of Clinical and Aesthetic Dermatology',
        'issn': '1941-2789',
        'publisher': 'Matrix Medical Communications'
    }

    def __init__(
        self,
        dtd_version: str = "2.3",
        dtd_public_id: str = '-//NLM//DTD Journal Publishing DTD v2.3 20070202//EN',
        dtd_path: Optional[str] = None
    ):
        """
        Initialize XMLGeneratorConfig with DTD settings.
        Args:
            dtd_version: DTD version (default: "2.3")
            dtd_public_id: Public identifier for the DTD
            dtd_path: Optional custom path to DTD directory
        """
        self.dtd_version = dtd_version
        self.dtd_public_id = dtd_public_id
        
        # Set and validate DTD paths
        self.dtd_base_path = self._resolve_dtd_path(dtd_path)
        self.dtd_file_path = self.dtd_base_path / 'journalpublishing.dtd'
        
        # Verify DTD setup
        self._verify_dtd_files()

    def _resolve_dtd_path(self, custom_path: Optional[str] = None) -> Path:
        """
        Resolve DTD directory path, checking multiple possible locations.
        """
        possible_paths = []
        
        # 1. Custom path if provided
        if custom_path:
            possible_paths.append(Path(custom_path))
            
        # 2. Default path relative to this file
        possible_paths.append(Path(__file__).parent.parent.parent / "config" / "nlm-dtd-2.3")
        
        # 3. Environment variable if set
        if 'PUBMED_DTD_PATH' in os.environ:
            possible_paths.append(Path(os.environ['PUBMED_DTD_PATH']))
            
        # Try each path
        for path in possible_paths:
            if path.exists() and path.is_dir():
                return path
                
        raise FileNotFoundError(
            f"DTD directory not found. Tried: {', '.join(str(p) for p in possible_paths)}"
        )

    def _verify_dtd_files(self):
        """
        Verify all required DTD and entity files are present and accessible.
        """
        missing_files = []
        
        for filename in self.REQUIRED_DTD_FILES:
            file_path = self.dtd_base_path / filename
            if not file_path.exists():
                missing_files.append(filename)
                
        if missing_files:
            raise FileNotFoundError(
                f"Missing required DTD files: {', '.join(missing_files)}\n"
                f"Expected location: {self.dtd_base_path}"
            )

    def get_catalog_path(self) -> Optional[str]:
        """
        Get path to XML catalog file if it exists.
        """
        catalog_path = self.dtd_base_path / 'catalog-v2.xml'
        return str(catalog_path) if catalog_path.exists() else None

    def get_doctype_declaration(self) -> str:
        """
        Generate DOCTYPE declaration with proper paths.
        """
        system_path = self.dtd_file_path.as_posix()  # Convert to forward slashes
        return (
            f'<!DOCTYPE article PUBLIC "{self.dtd_public_id}" '
            f'"{system_path}">\n'
        )

class XMLGenerator:
    """
    Enhanced XML generator for PubMed 2.3 DTD compliance.
    Creates fully structured XML with proper namespaces and validation.
    """

    def __init__(self, config: Optional[XMLGeneratorConfig] = None):
        self.config = config or XMLGeneratorConfig()
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

    def generate(
        self,
        journal_meta: JournalMetadata,
        article_meta: ArticleMetadata,
        processed_content: ProcessedContent
    ) -> str:
        """
        Main entry point to generate a PubMed-style XML string.

        Args:
            journal_meta: JournalMetadata from metadata_extractor.
            article_meta: ArticleMetadata from metadata_extractor.
            processed_content: ProcessedContent from text_processor.

        Returns:
            A string containing the final XML (with DOCTYPE).
        """
        self.logger.info("Starting XML generation.")

        # 1. Create root <article> with proper namespaces
        # Define XML namespaces
        nsmap = {
            'xlink': 'http://www.w3.org/1999/xlink',
            'xml': 'http://www.w3.org/XML/1998/namespace'
        }
        root = etree.Element("article", nsmap=nsmap)
        root.set("dtd-version", self.config.dtd_version)
        root.set("article-type", article_meta.article_type or "research-article")
        # Set xml:lang attribute using proper namespace
        root.set("{http://www.w3.org/XML/1998/namespace}lang", "en")

        # 2. Build <front> (journal-meta, article-meta)
        front = etree.SubElement(root, "front")
        self._build_journal_meta(front, journal_meta)
        self._build_article_meta(front, article_meta, processed_content)

        # 3. Build <body> from processed_content.sections
        body = etree.SubElement(root, "body")
        self._build_body(body, processed_content)

        # 4. Build <back> with references (if any)
        back = etree.SubElement(root, "back")
        if processed_content.references:
            self._build_references(back, processed_content.references)

        # 5. Final validation to ensure required elements exist
        self._ensure_required_elements(root, journal_meta, article_meta, processed_content)

        # 6. Convert the element tree to a string with DOCTYPE
        xml_string = self._generate_xml_string(root)

        self.logger.info("XML generation complete.")
        return xml_string

    # ----------------------------------------------------------------------
    # FRONT: Journal + Article Metadata
    # ----------------------------------------------------------------------

    def _build_journal_meta(self, parent: etree.Element, jmeta: JournalMetadata) -> None:
        """Create <journal-meta> element with journal metadata."""
        journal_meta_elem = etree.SubElement(parent, "journal-meta")

        # Always use JCAD data for consistency
        journal_id_elem = etree.SubElement(journal_meta_elem, "journal-id")
        journal_id_elem.set("journal-id-type", "publisher-id")
        journal_id_elem.text = self.config.JOURNAL_METADATA['id']

        # Journal title
        jtitle_group = etree.SubElement(journal_meta_elem, "journal-title-group")
        jtitle = etree.SubElement(jtitle_group, "journal-title")
        jtitle.text = self.config.JOURNAL_METADATA['title']

        # ISSN
        issn_elem = etree.SubElement(journal_meta_elem, "issn")
        issn_elem.set("pub-type", "ppub")
        issn_elem.text = self.config.JOURNAL_METADATA['issn']

        # Publisher
        publisher_elem = etree.SubElement(journal_meta_elem, "publisher")
        publisher_name = etree.SubElement(publisher_elem, "publisher-name")
        publisher_name.text = self.config.JOURNAL_METADATA['publisher']

    def _build_article_meta(self, parent: etree.Element, ameta: ArticleMetadata, content: ProcessedContent) -> None:
        """Create complete <article-meta> with all required PubMed elements."""
        article_meta_elem = etree.SubElement(parent, "article-meta")

        # 1. Article IDs
        self._build_article_ids(article_meta_elem, ameta)
        
        # 2. Article Categories
        self._build_article_categories(article_meta_elem, ameta)
        
        # 3. Title Group
        self._build_title_group(article_meta_elem, ameta)
        
        # 4. Contributing Group (authors with degrees)
        self._build_contrib_group(article_meta_elem, ameta)
        
        # 5. Author Notes (correspondence, funding, conflicts)
        self._build_author_notes(article_meta_elem, ameta)
        
        # 6. Publication Dates
        self._build_pub_dates(article_meta_elem, ameta)
        
        # 7. Volume/Issue/Pagination
        self._build_issue_data(article_meta_elem, ameta)
        
        # 8. Abstract and Keywords
        self._build_abstract_block(article_meta_elem, content)
        
        # 9. Permissions Block
        self._build_permissions(article_meta_elem, ameta)

    def _build_article_ids(self, parent: etree.Element, ameta: ArticleMetadata) -> None:
        """Build article identifiers section."""
        # Generate article ID if not provided
        article_id = ameta.article_id
        if not article_id:
            # Try to create a meaningful ID based on title or current timestamp
            if ameta.title and ameta.title != "Untitled":
                # Convert title to slug-like ID (lowercase, only alphanumeric and underscore)
                slug = re.sub(r'[^a-z0-9]', '_', ameta.title.lower())
                slug = re.sub(r'_+', '_', slug)  # Replace multiple underscores with one
                article_id = slug[:50]  # Limit length
            else:
                # Use timestamp if no meaningful title
                article_id = f"article-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Add the publisher ID
        id_elem = etree.SubElement(parent, "article-id")
        id_elem.set("pub-id-type", "publisher-id")
        id_elem.text = article_id
        
        # DOI if available
        if ameta.doi:
            doi_elem = etree.SubElement(parent, "article-id")
            doi_elem.set("pub-id-type", "doi")
            doi_elem.text = ameta.doi

    def _build_article_categories(self, parent: etree.Element, ameta: ArticleMetadata) -> None:
        """Build article categories section."""
        categories = etree.SubElement(parent, "article-categories")
        subj_group = etree.SubElement(categories, "subj-group")
        
        # Add primary category based on article type
        subject = etree.SubElement(subj_group, "subject")
        if ameta.article_type == "research-article":
            subject.text = "Original Research"
        elif ameta.article_type == "review-article" or ameta.article_type == "review":
            subject.text = "Review Article"
        elif ameta.article_type == "case-report":
            subject.text = "Case Report"
        elif ameta.article_type == "letter":
            subject.text = "Letter to the Editor"
        elif ameta.article_type == "editorial":
            subject.text = "Editorial"
        elif ameta.article_type == "abstract":
            subject.text = "Abstract"
        else:
            # If keywords available, use first one as subject
            if hasattr(ameta, 'keywords') and ameta.keywords:
                subject.text = ameta.keywords[0]
            else:
                # Default fallback - use capitalized article type
                subject.text = ameta.article_type.replace("-", " ").title()

    def _build_title_group(self, parent: etree.Element, ameta: ArticleMetadata) -> None:
        """Build title group with main title."""
        title_group = etree.SubElement(parent, "title-group")
        
        # Main article title
        article_title = etree.SubElement(title_group, "article-title")
        
        # Clean title text - replace character entities
        title_text = ameta.title or "Untitled Article"
        title_text = self._clean_text_for_xml(title_text)
        
        article_title.text = title_text

    def _clean_text_for_xml(self, text: str) -> str:
        """Clean text for XML by replacing problematic characters."""
        if not text:
            return ""
            
        # Replace common characters that need entities
        replacements = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&apos;',
        }
        
        for char, entity in replacements.items():
            text = text.replace(char, entity)
            
        return text

    def _build_contrib_group(self, parent: etree.Element, ameta: ArticleMetadata) -> None:
        """Build contributor group with complete author information."""
        # Skip if no authors
        if not ameta.authors:
            return
            
        contrib_group = etree.SubElement(parent, "contrib-group")
        
        # Track all unique affiliations
        all_affiliations = {}
        for author in ameta.authors:
            for aff in author.affiliations:
                if aff and aff not in all_affiliations:
                    all_affiliations[aff] = len(all_affiliations) + 1
        
        # Add each author
        for i, author in enumerate(ameta.authors):
            contrib = etree.SubElement(contrib_group, "contrib")
            contrib.set("contrib-type", "author")
            
            # Set corresponding author flag
            is_corresponding = False
            if ameta.corresponding_author:
                author_name = f"{author.given_names} {author.surname}"
                if author_name in ameta.corresponding_author:
                    is_corresponding = True
                elif author.email and author.email in ameta.corresponding_author:
                    is_corresponding = True
            
            if is_corresponding:
                contrib.set("corresp", "yes")
            
            # Name components
            name = etree.SubElement(contrib, "name")
            surname = etree.SubElement(name, "surname")
            surname.text = author.surname
            given_names = etree.SubElement(name, "given-names")
            given_names.text = author.given_names
            
            # Degrees/credentials if available
            if author.credentials:
                degrees = etree.SubElement(contrib, "degrees")
                degrees.text = author.credentials
            
            # Email if available
            if author.email:
                email = etree.SubElement(contrib, "email")
                email.text = author.email
            
            # Add affiliation references
            for aff_text in author.affiliations:
                if aff_text in all_affiliations:
                    aff_id = all_affiliations[aff_text]
                    xref = etree.SubElement(contrib, "xref")
                    xref.set("ref-type", "aff")
                    xref.set("rid", f"aff{aff_id}")
                    xref.text = str(aff_id)
        
        # Add all affiliations at the end of contrib-group
        for aff_text, aff_id in all_affiliations.items():
            aff = etree.SubElement(contrib_group, "aff")
            aff.set("id", f"aff{aff_id}")
            
            # Add label
            label = etree.SubElement(aff, "label")
            label.text = str(aff_id)
            
            # Add affiliation text
            aff.text = aff_text

    def _build_author_notes(self, parent: etree.Element, ameta: ArticleMetadata) -> None:
        """Build author notes including correspondence and disclosures."""
        # Skip if no notes
        if not (ameta.corresponding_author or ameta.funding_statement or ameta.conflict_statement):
            return
            
        notes = etree.SubElement(parent, "author-notes")
        
        # Correspondence
        if ameta.corresponding_author:
            corresp = etree.SubElement(notes, "fn")
            corresp.set("fn-type", "corresp")
            
            p = etree.SubElement(corresp, "p")
            # Add label
            bold = etree.SubElement(p, "bold")
            bold.text = "CORRESPONDENCE:"
            # Add space after label
            if p.text is None:
                p.text = " "
            else:
                p.text += " "
            
            # Add correspondence info
            if ameta.corresponding_author:
                p.text = p.text + ameta.corresponding_author
        
        # Funding
        if ameta.funding_statement:
            fn = etree.SubElement(notes, "fn")
            fn.set("fn-type", "financial-disclosure")
            
            # Add label
            label = etree.SubElement(fn, "label")
            label.text = "FUNDING:"
            
            p = etree.SubElement(fn, "p")
            p.text = ameta.funding_statement
        
        # Conflicts
        if ameta.conflict_statement:
            fn = etree.SubElement(notes, "fn")
            fn.set("fn-type", "conflict")
            
            # Add label
            label = etree.SubElement(fn, "label")
            label.text = "DISCLOSURES:"
            
            p = etree.SubElement(fn, "p")
            p.text = ameta.conflict_statement

    def _build_pub_dates(self, parent: etree.Element, ameta: ArticleMetadata) -> None:
        """Build publication dates section."""
        # Create pub-date element
        pub_date = etree.SubElement(parent, "pub-date")
        pub_date.set("pub-type", "ppub")
        
        # Add available date parts
        if ameta.publication_date:
            # First check if we have a month name/season
            if 'month' in ameta.publication_date:
                month_value = ameta.publication_date['month']
                
                # Check if it's a numeric month or name
                if month_value.isdigit():
                    # Convert numeric month to name
                    try:
                        month_num = int(month_value)
                        if 1 <= month_num <= 12:
                            month_names = [
                                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
                            ]
                            season = etree.SubElement(pub_date, "season")
                            season.text = month_names[month_num - 1]
                    except ValueError:
                        # If conversion fails, just use as-is
                        month = etree.SubElement(pub_date, "month")
                        month.text = month_value
                else:
                    # Non-numeric month - use as season
                    season = etree.SubElement(pub_date, "season")
                    season.text = month_value
            
            # Year is required
            if 'year' in ameta.publication_date:
                year = etree.SubElement(pub_date, "year")
                year.text = ameta.publication_date['year']
            else:
                # Default to current year if missing
                year = etree.SubElement(pub_date, "year")
                year.text = str(datetime.now().year)
            
            # Add day if available
            if 'day' in ameta.publication_date:
                day = etree.SubElement(pub_date, "day")
                day.text = ameta.publication_date['day']
        else:
            # Default to current year
            year = etree.SubElement(pub_date, "year")
            year.text = str(datetime.now().year)

    def _build_issue_data(self, parent: etree.Element, ameta: ArticleMetadata) -> None:
        """Build volume, issue, and page number elements."""
        if ameta.volume:
            vol_elem = etree.SubElement(parent, "volume")
            vol_elem.text = ameta.volume

        if ameta.issue:
            issue_elem = etree.SubElement(parent, "issue")
            issue_elem.text = ameta.issue

        if ameta.fpage:
            fpage_elem = etree.SubElement(parent, "fpage")
            fpage_elem.text = ameta.fpage
            
            if ameta.lpage:
                lpage_elem = etree.SubElement(parent, "lpage")
                lpage_elem.text = ameta.lpage

    def _build_abstract_block(self, parent: etree.Element, content: ProcessedContent) -> None:
        """Build abstract and keywords section."""
        # Add abstract if present
        if content.abstract:
            abstract_elem = etree.SubElement(parent, "abstract")
            
            # Clean abstract text
            abstract_text = self._clean_text_for_xml(content.abstract)
            
            # If abstract has paragraphs, split them
            paragraphs = abstract_text.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    p_elem = etree.SubElement(abstract_elem, "p")
                    p_elem.text = para.strip()
        
        # Add keywords if present
        if hasattr(content, 'keywords') and content.keywords:
            kwd_group = etree.SubElement(parent, "kwd-group")
            for kw in content.keywords:
                kwd_elem = etree.SubElement(kwd_group, "kwd")
                kwd_elem.text = kw.strip()

    def _build_permissions(self, parent: etree.Element, ameta: ArticleMetadata) -> None:
        """Build permissions block with copyright information."""
        permissions = etree.SubElement(parent, "permissions")
        
        # Copyright statement
        copyright_year = ameta.publication_date.get("year", datetime.now().year)
        publisher_name = self.config.JOURNAL_METADATA['publisher']
        
        copyright_statement = etree.SubElement(permissions, "copyright-statement")
        copyright_statement.text = f"Copyright © {copyright_year}. {publisher_name}. All rights reserved."
        
        copyright_year_elem = etree.SubElement(permissions, "copyright-year")
        copyright_year_elem.text = str(copyright_year)
        
        copyright_holder = etree.SubElement(permissions, "copyright-holder")
        copyright_holder.text = publisher_name

    def _build_references(self, parent: etree.Element, references: List[ReferenceData]) -> None:
        """
        Create <ref-list> with detailed reference entries.
        """
        # Skip if no references
        if not references:
            return
            
        # Create reference list
        ref_list = etree.SubElement(parent, "ref-list")
        
        # Title for reference list
        title = etree.SubElement(ref_list, "title")
        title.text = "REFERENCES"
        
        # Add each reference
        for i, ref in enumerate(references, 1):
            # Get reference ID - use ref.ref_id if available, otherwise use index
            ref_id = ref.ref_id or str(i)
            
            ref_elem = etree.SubElement(ref_list, "ref")
            ref_elem.set("id", f"B{ref_id}")  # Using B prefix for bibliography
            
            # Create mixed-citation element
            mixed_citation = etree.SubElement(ref_elem, "mixed-citation")
            mixed_citation.set("publication-type", ref.reference_type or "journal")
            
            # If we have structured data, build structured citation
            if ref.authors or ref.year or ref.title or ref.journal:
                self._build_structured_citation(mixed_citation, ref)
            else:
                # Just use raw text if no structured data
                mixed_citation.text = self._clean_text_for_xml(ref.raw_text)

    def _build_structured_citation(self, parent: etree.Element, ref: ReferenceData) -> None:
        """Build a structured citation with parsed components."""
        # Track the last element added to set tails correctly
        last_elem = None
        
        # 1. Authors
        if ref.authors:
            for i, author in enumerate(ref.authors):
                # Add separator between authors
                if i > 0:
                    if i == len(ref.authors) - 1:
                        # Last author - add "and"
                        if last_elem is not None:
                            last_elem.tail = " and "
                        else:
                            parent.text = parent.text + " and " if parent.text else " and "
                    else:
                        # Not last author - add comma
                        if last_elem is not None:
                            last_elem.tail = ", "
                        else:
                            parent.text = parent.text + ", " if parent.text else ", "
                
                # Parse author name
                name_parts = author.split(",", 1)
                if len(name_parts) == 2:
                    surname = name_parts[0].strip()
                    given_names = name_parts[1].strip()
                else:
                    name_words = author.split()
                    if len(name_words) > 1:
                        surname = name_words[-1]
                        given_names = " ".join(name_words[:-1])
                    else:
                        surname = author
                        given_names = ""
                
                # Create name element
                name_elem = etree.SubElement(parent, "string-name")
                
                # Add surname
                surname_elem = etree.SubElement(name_elem, "surname")
                surname_elem.text = surname.strip()
                
                # Add given names if available
                if given_names:
                    given_elem = etree.SubElement(name_elem, "given-names")
                    given_elem.text = given_names.strip()
                
                # Update last element
                last_elem = name_elem
        
        # 2. Year
        if ref.year:
            # Add separator after authors
            if last_elem is not None:
                last_elem.tail = last_elem.tail + " " if last_elem.tail else " "
                last_elem.tail += f"({ref.year})"
            else:
                parent.text = parent.text + " " if parent.text else ""
                parent.text += f"({ref.year})"
            
            # No element added for year, keep last_elem the same
        
        # 3. Title
        if ref.title:
            # Add period after authors/year
            if last_elem is not None:
                last_elem.tail = last_elem.tail + ". " if last_elem.tail else ". "
            else:
                parent.text = parent.text + ". " if parent.text else ""
            
            # Create article-title element
            article_title = etree.SubElement(parent, "article-title")
            article_title.text = ref.title.strip()
            
            # Update last element
            last_elem = article_title
        
        # 4. Journal
        if ref.journal:
            # Add period after title
            if last_elem is not None:
                last_elem.tail = last_elem.tail + ". " if last_elem.tail else ". "
            else:
                parent.text = parent.text + ". " if parent.text else ""
            
            # Create source element
            source = etree.SubElement(parent, "source")
            source.text = ref.journal.strip()
            
            # Update last element
            last_elem = source
        
        # 5. Volume/Issue/Pages
        vol_issue_added = False
        
        # Add volume if available
        if ref.volume:
            # Add space after journal
            if last_elem is not None:
                last_elem.tail = last_elem.tail + " " if last_elem.tail else " "
            else:
                parent.text = parent.text + " " if parent.text else ""
            
            # Create volume element
            volume = etree.SubElement(parent, "volume")
            volume.text = ref.volume.strip()
            
            # Update last element
            last_elem = volume
            vol_issue_added = True
            
            # Add issue if available
            if ref.issue:
                last_elem.tail = last_elem.tail + "(" if last_elem.tail else "("
                
                # Create issue element
                issue = etree.SubElement(parent, "issue")
                issue.text = ref.issue.strip()
                
                # Add closing parenthesis
                issue.tail = ")"
                
                # Update last element
                last_elem = issue
                vol_issue_added = True
        
        # Add pages if available
        if ref.pages:
            # Add separator after volume/issue
            if vol_issue_added:
                if last_elem is not None:
                    last_elem.tail = last_elem.tail + ":" if last_elem.tail else ":"
                else:
                    parent.text = parent.text + ":" if parent.text else ""
            else:
                # No volume/issue - add space if needed
                if last_elem is not None:
                    last_elem.tail = last_elem.tail + " " if last_elem.tail else " "
                else:
                    parent.text = parent.text + " " if parent.text else ""
            
            # Try to split pages into first and last
            if "-" in ref.pages:
                fpage, lpage = ref.pages.split("-", 1)
                
                # Create fpage element
                fpage_elem = etree.SubElement(parent, "fpage")
                fpage_elem.text = fpage.strip()
                
                # Add hyphen
                fpage_elem.tail = "-"
                
                # Create lpage element
                lpage_elem = etree.SubElement(parent, "lpage")
                lpage_elem.text = lpage.strip()
                
                # Update last element
                last_elem = lpage_elem
            else:
                # Single page - use fpage only
                fpage_elem = etree.SubElement(parent, "fpage")
                fpage_elem.text = ref.pages.strip()
                
                # Update last element
                last_elem = fpage_elem
        
        # 6. DOI
        if ref.doi:
            # Add period after volume/issue/pages
            if last_elem is not None:
                last_elem.tail = last_elem.tail + ". " if last_elem.tail else ". "
            else:
                parent.text = parent.text + ". " if parent.text else ""
            
            # Create pub-id element
            pub_id = etree.SubElement(parent, "pub-id")
            pub_id.set("pub-id-type", "doi")
            pub_id.text = ref.doi.strip()
            
            # Update last element
            last_elem = pub_id
        
        # Ensure final period
        if last_elem is not None and not (last_elem.tail and last_elem.tail.rstrip().endswith('.')):
            last_elem.tail = last_elem.tail + "." if last_elem.tail else "."

    def _ensure_required_elements(self, root: etree.Element, 
                                journal_meta: JournalMetadata, 
                                article_meta: ArticleMetadata,
                                content: ProcessedContent) -> None:
        """
        Final validation to ensure all required elements are present.
        Add any missing critical elements.
        """
        # 1. Ensure journal metadata is correct (JCAD)
        journal_id = root.find(".//journal-id")
        if journal_id is not None:
            journal_id.text = self.config.JOURNAL_METADATA['id']
            
        journal_title = root.find(".//journal-title")
        if journal_title is not None:
            journal_title.text = self.config.JOURNAL_METADATA['title']
            
        issn = root.find(".//issn")
        if issn is None:
            # Add ISSN if missing
            journal_meta_elem = root.find(".//journal-meta")
            if journal_meta_elem is not None:
                issn = etree.SubElement(journal_meta_elem, "issn")
                issn.set("pub-type", "ppub")
                issn.text = self.config.JOURNAL_METADATA['issn']
        
        # 2. Ensure article title exists
        title_group = root.find(".//title-group")
        article_title = root.find(".//article-title")
        if title_group is not None and article_title is None:
            # Add article title
            article_title = etree.SubElement(title_group, "article-title")
            article_title.text = article_meta.title or "Untitled Article"
        
        # 3. Ensure at least one author exists
        contrib_group = root.find(".//contrib-group")
        if contrib_group is not None and len(contrib_group.findall(".//contrib")) == 0:
            # Add placeholder author if none exists
            contrib = etree.SubElement(contrib_group, "contrib")
            contrib.set("contrib-type", "author")
            
            name = etree.SubElement(contrib, "name")
            surname = etree.SubElement(name, "surname")
            surname.text = "Unknown"
            given_names = etree.SubElement(name, "given-names")
            given_names.text = "Author"
        
        # 4. Ensure body has content
        body = root.find(".//body")
        if body is not None and len(body) == 0:
            # Add at least one section with content
            sec = etree.SubElement(body, "sec")
            p = etree.SubElement(sec, "p")
            p.text = "Article content not available."
            
        # 5. Ensure publication date has a year
        pub_date = root.find(".//pub-date")
        if pub_date is not None and pub_date.find(".//year") is None:
            # Add current year
            year = etree.SubElement(pub_date, "year")
            year.text = str(datetime.now().year)
            
        # 6. Ensure permissions exist
        permissions = root.find(".//permissions")
        if permissions is None:
            # Add permissions block
            article_meta_elem = root.find(".//article-meta")
            if article_meta_elem is not None:
                permissions = etree.SubElement(article_meta_elem, "permissions")
                
                # Add copyright statement
                copyright_year = datetime.now().year
                publisher_name = self.config.JOURNAL_METADATA['publisher']
                
                copyright_statement = etree.SubElement(permissions, "copyright-statement")
                copyright_statement.text = f"Copyright © {copyright_year}. {publisher_name}. All rights reserved."
                
                copyright_year_elem = etree.SubElement(permissions, "copyright-year")
                copyright_year_elem.text = str(copyright_year)
                
                copyright_holder = etree.SubElement(permissions, "copyright-holder")
                copyright_holder.text = publisher_name

    def _generate_xml_string(self, root: etree.Element) -> str:
        """
        Convert the lxml ElementTree to a string, including XML declaration
        and DOCTYPE referencing the local DTD.
        """
        # 1. Create XML declaration
        xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'

        # 2. Get DOCTYPE from config
        doctype_str = self.config.get_doctype_declaration()

        # 3. Convert the XML tree to a string (without its own XML declaration)
        xml_content = etree.tostring(
            root,
            encoding='unicode',
            pretty_print=True,
            xml_declaration=False
        )

        # 4. Combine all parts
        final_xml = xml_declaration + doctype_str + xml_content
        return final_xml

    def _build_body(self, parent: etree.Element, content: ProcessedContent) -> None:
        """
        Create <body> with <sec> elements for each section in ProcessedContent.
        """
        # Skip if no sections
        if not content.sections:
            # Add empty paragraph to ensure valid XML
            sec_elem = etree.SubElement(parent, "sec")
            p_elem = etree.SubElement(sec_elem, "p")
            p_elem.text = "Article content not available."
            return
            
        # Create sections for each in processed_content
        for section in content.sections:
            # Skip empty sections
            if not section.paragraphs and not section.title:
                continue
                
            sec_elem = etree.SubElement(parent, "sec")
            
            # Add section title if present
            if section.title and section.title.strip():
                title_elem = etree.SubElement(sec_elem, "title")
                title_elem.text = section.title.strip()

            # Convert each paragraph to <p>
            for paragraph in section.paragraphs:
                if not paragraph or not paragraph.strip():
                    continue
                    
                p_elem = etree.SubElement(sec_elem, "p")
                
                # Process paragraph for citations
                paragraph = self._clean_text_for_xml(paragraph)
                
                # Check for citation references like [1], [2], etc.
                if self._has_citation_refs(paragraph):
                    # Process paragraph with citations
                    self._process_paragraph_with_citations(p_elem, paragraph)
                else:
                    # Simple paragraph without citations
                    p_elem.text = paragraph.strip()

    def _has_citation_refs(self, text: str) -> bool:
        """Check if paragraph contains citation references."""
        citation_patterns = [
            r'\[\d+\]',                      # [1]
            r'\[\d+(?:[-,]\d+)*\]',          # [1,2] or [1-3]
            r'\(\d{4}\)',                    # (2020)
            r'\([A-Za-z]+ et al\.\)',        # (Smith et al.)
            r'\([A-Za-z]+ and [A-Za-z]+, \d{4}\)'  # (Smith and Jones, 2020)
        ]
        
        return any(re.search(pattern, text) for pattern in citation_patterns)

    def _process_paragraph_with_citations(self, parent: etree.Element, text: str) -> None:
        """
        Parse a paragraph with citation references.
        Converts [1], [2], etc. to <xref ref-type="bibr" rid="B1">[1]</xref>
        """
        # Pattern for [n] style references
        numeric_pattern = re.compile(r'\[(\d+(?:[-,]\d+)*)\]')
        
        # Find all citation matches
        matches = list(numeric_pattern.finditer(text))
        
        if not matches:
            # No numeric citations found, just set the text
            parent.text = text
            return
            
        # Sort matches by position (from end to beginning)
        matches.sort(key=lambda m: m.start(), reverse=True)
        
        # Replace each citation from end to beginning
        for match in matches:
            ref_nums = match.group(1)
            start = match.start()
            end = match.end()
            
            # Check if we're dealing with a range or comma-separated list
            if '-' in ref_nums:
                # Range like [1-3]
                start_num, end_num = ref_nums.split('-')
                ref_ids = list(range(int(start_num), int(end_num) + 1))
                ref_primary = start_num  # Use first number for the rid
            elif ',' in ref_nums:
                # List like [1,2,3]
                ref_ids = [int(n) for n in ref_nums.split(',')]
                ref_primary = ref_nums.split(',')[0]  # Use first number
            else:
                # Single reference [1]
                ref_ids = [int(ref_nums)]
                ref_primary = ref_nums
            
            # Text before and after this citation
            pre_text = text[:start]
            post_text = text[end:]
            
            # Create a placeholder for this citation
            text = pre_text + f"__CITATION_R{ref_primary}__" + post_text
        
        # Process the modified text with placeholders
        parts = re.split(r'(__CITATION_R\d+__)', text)
        
        # First part is regular text
        parent.text = parts[0] if parts else ""
        
        # Process all parts
        current_element = parent
        
        for i in range(1, len(parts), 2):
            if i >= len(parts):
                break
                
            # Get citation placeholder
            placeholder = parts[i]
            ref_num = placeholder.replace("__CITATION_R", "").replace("__", "")
            
            # Create xref element
            xref = etree.SubElement(current_element, "xref")
            xref.set("ref-type", "bibr")
            xref.set("rid", f"B{ref_num}")  # Using B for bibliography/reference
            xref.text = f"[{ref_num}]"
            
            # Set text after this citation (if any)
            if i + 1 < len(parts):
                xref.tail = parts[i + 1]
            
            # Update current element
            current_element = xref