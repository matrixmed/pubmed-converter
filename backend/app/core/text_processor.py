import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from .pdf_extractor import ExtractedContent

@dataclass
class ProcessedSection:
    """A high-level section of the article (e.g. INTRODUCTION, METHODS, etc.)."""
    title: str
    paragraphs: List[str] = field(default_factory=list)

@dataclass
class ReferenceData:
    """Enhanced reference data structure."""
    raw_text: str
    ref_id: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[str] = None
    title: Optional[str] = None
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    citations: List[str] = field(default_factory=list)  # Track where this reference is cited
    reference_type: str = "journal"  # journal, book, web, etc.

@dataclass
class ProcessedContent:
    """
    Final structured content after text processing:
      - title, abstract (if you want to confirm or refine it here)
      - list of sections (intro, methods, results, etc.)
      - references
    """
    title: str
    abstract: Optional[str] = None
    sections: List[ProcessedSection] = field(default_factory=list)
    references: List[ReferenceData] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

class TextProcessor:
    """
    Enhanced text processor that leverages GROBID's structured extraction
    with additional post-processing to clean and format content.
    """
    
    def __init__(self):
        self._setup_logging()
        self._setup_patterns()

    def _setup_logging(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            self.logger.addHandler(handler)
            
    def _setup_patterns(self):
        """Initialize regex and processing patterns."""
        # Common section headings in medical articles
        self.SECTION_HEADINGS = [
            'ABSTRACT', 'INTRODUCTION', 'BACKGROUND',
            'METHODS', 'MATERIALS AND METHODS', 'METHODOLOGY',
            'RESULTS', 'FINDINGS', 'OUTCOMES',
            'DISCUSSION', 'CONCLUSION', 'CONCLUSIONS',
            'REFERENCES', 'ACKNOWLEDGMENTS'
        ]
        
        # Pattern for identifying heading candidates
        self.heading_pattern = re.compile(
            r'^(?:\d+\.?\s*)?(' + '|'.join(self.SECTION_HEADINGS) + r')',
            re.IGNORECASE
        )
        
        # Pattern for identifying reference citations
        self.citation_pattern = re.compile(
            r'(?:\[(\d+(?:[,-]\d+)*)\])|'  # [1] or [1,2] or [1-3]
            r'(?:\(([^)]+?(?:\d{4})[^)]*?)\))'  # (Author et al., 2020)
        )

    def process(
        self,
        extracted_content: ExtractedContent,
        article_title: str,
        abstract: Optional[str] = None
    ) -> ProcessedContent:
        """
        Main method to process GROBID-extracted content into final structured content.
        
        Args:
            extracted_content: The GROBID-extracted content from PDFExtractor.
            article_title: The article title (from metadata_extractor).
            abstract: The article abstract (from metadata_extractor or user input).

        Returns:
            ProcessedContent with structured sections + references.
        """
        self.logger.info("Starting text processing with enhanced processing.")
        
        # 1. Use GROBID-extracted title and abstract if available and not overridden
        title = article_title or extracted_content.title or "Untitled Article"
        abstract_text = abstract or extracted_content.abstract
        
        # 2. Convert GROBID sections to ProcessedSections
        sections = self._process_sections(extracted_content)
        
        # 3. Convert GROBID references to ReferenceData
        references = self._process_references(extracted_content)
        
        # 4. Extract keywords if available
        keywords = self._extract_keywords(extracted_content)
        
        # 5. Apply post-processing to clean up content
        sections = self._post_process_sections(sections)
        references = self._post_process_references(references)
        
        # 6. Build the final processed content
        processed_content = ProcessedContent(
            title=title,
            abstract=abstract_text,
            sections=sections,
            references=references,
            keywords=keywords
        )

        self.logger.info("Text processing complete.")
        return processed_content

    def _process_sections(self, content: ExtractedContent) -> List[ProcessedSection]:
        """
        Convert GROBID-extracted sections to ProcessedSections.
        Enhanced to handle better section detection and cleaning.
        """
        processed_sections = []
        
        # If GROBID extracted sections, use them
        if content.sections:
            for section in content.sections:
                # Skip sections without meaningful content
                if not section.get('paragraphs') and not section.get('title'):
                    continue
                    
                # Clean section title
                title = section.get('title', '').strip()
                
                # Fix title case if all uppercase
                if title.isupper():
                    title = title.title()
                
                # Process paragraphs
                paragraphs = []
                for p in section.get('paragraphs', []):
                    # Clean paragraph text
                    cleaned_p = self._clean_paragraph(p)
                    if cleaned_p:
                        paragraphs.append(cleaned_p)
                
                if title or paragraphs:
                    processed_sections.append(ProcessedSection(
                        title=title,
                        paragraphs=paragraphs
                    ))
        
        # If no sections from GROBID, try to extract from raw text
        if not processed_sections and content.raw_text:
            # Try to identify sections from raw text
            sections_from_text = self._extract_sections_from_raw_text(content.raw_text)
            if sections_from_text:
                processed_sections = sections_from_text
        
        # If still no sections, create a single section with all content
        if not processed_sections and content.raw_text:
            # Split raw text into paragraphs
            raw_paragraphs = self._split_into_paragraphs(content.raw_text)
            processed_sections.append(ProcessedSection(
                title="",
                paragraphs=raw_paragraphs
            ))
            
        return processed_sections

    def _process_references(self, content: ExtractedContent) -> List[ReferenceData]:
        """
        Convert GROBID-extracted references to ReferenceData.
        Enhanced with better parsing of reference components.
        """
        processed_refs = []
        
        # Process each GROBID reference
        for ref in content.references:
            # Skip empty references
            if not ref.get('raw_text'):
                continue
                
            # Convert to ReferenceData format
            ref_data = ReferenceData(
                raw_text=ref.get('raw_text', ''),
                ref_id=ref.get('ref_id'),
                authors=ref.get('authors', []),
                year=ref.get('year'),
                title=ref.get('title'),
                journal=ref.get('journal'),
                volume=ref.get('volume'),
                issue=ref.get('issue'),
                pages=ref.get('pages'),
                doi=ref.get('doi')
            )
            
            # Try to extract more info if fields are missing
            if not (ref_data.authors and ref_data.title and ref_data.journal):
                self._enhance_reference_data(ref_data)
            
            processed_refs.append(ref_data)
            
        # If no references from GROBID, try to extract from raw text
        if not processed_refs and content.raw_text:
            processed_refs = self._extract_references_from_raw_text(content.raw_text)
            
        return processed_refs

    def _extract_keywords(self, content: ExtractedContent) -> List[str]:
        """Extract keywords from extracted content."""
        keywords = []
        
        # Look for keywords section in raw text
        if content.raw_text:
            keyword_patterns = [
                r'(?:Key\s*words?|Keywords?)[:\-]+\s*(.+?)(?:\n\n|\n[A-Z])',
                r'(?:Key\s*words?|Keywords?)[:\-]+\s*(.+?)\.'
            ]
            
            for pattern in keyword_patterns:
                match = re.search(pattern, content.raw_text, re.IGNORECASE | re.DOTALL)
                if match:
                    keyword_text = match.group(1).strip()
                    # Split on commas or semicolons
                    keyword_parts = re.split(r'[;,]', keyword_text)
                    keywords = [p.strip() for p in keyword_parts if p.strip()]
                    break
        
        return keywords

    def _post_process_sections(self, sections: List[ProcessedSection]) -> List[ProcessedSection]:
        """
        Apply additional cleaning and formatting to sections:
        - Remove duplicate paragraphs
        - Clean up whitespace
        - Merge partial paragraphs
        - Remove page numbers and headers/footers
        """
        cleaned_sections = []
        
        for section in sections:
            # Skip empty sections
            if not section.title and not section.paragraphs:
                continue
                
            cleaned_paragraphs = []
            seen_paragraphs = set()
            
            for p in section.paragraphs:
                # Skip empty paragraphs
                if not p.strip():
                    continue
                    
                # Clean paragraph
                p = self._clean_paragraph(p)
                
                # Skip very short paragraphs that look like page numbers
                if len(p) < 10 and p.strip().isdigit():
                    continue
                    
                # Skip common headers/footers
                if self._is_header_footer(p):
                    continue
                
                # Skip duplicates
                if p in seen_paragraphs:
                    continue
                    
                seen_paragraphs.add(p)
                cleaned_paragraphs.append(p)
            
            # Only add section if it has content
            if cleaned_paragraphs or section.title:
                cleaned_sections.append(ProcessedSection(
                    title=section.title,
                    paragraphs=cleaned_paragraphs
                ))
                
        return cleaned_sections

    def _post_process_references(self, references: List[ReferenceData]) -> List[ReferenceData]:
        """
        Clean and enhance references:
        - Remove duplicates
        - Ensure unique ref_ids
        - Fix common formatting issues
        """
        # Skip if no references
        if not references:
            return references
            
        # Clean each reference
        for ref in references:
            # Ensure ref_id exists
            if not ref.ref_id:
                ref.ref_id = str(references.index(ref) + 1)
            
            # Clean raw_text
            if ref.raw_text:
                ref.raw_text = re.sub(r'\s+', ' ', ref.raw_text).strip()
            
            # Clean title
            if ref.title:
                ref.title = re.sub(r'\s+', ' ', ref.title).strip()
                # Remove period at end if present
                if ref.title.endswith('.'):
                    ref.title = ref.title[:-1]
            
            # Clean journal
            if ref.journal:
                ref.journal = re.sub(r'\s+', ' ', ref.journal).strip()
        
        # Remove duplicates by raw_text
        unique_refs = []
        seen_texts = set()
        
        for ref in references:
            if ref.raw_text and ref.raw_text in seen_texts:
                continue
                
            if ref.raw_text:
                seen_texts.add(ref.raw_text)
                
            unique_refs.append(ref)
            
        return unique_refs

    def _clean_paragraph(self, text: str) -> str:
        """
        Clean a paragraph by fixing common issues:
        - Normalize whitespace
        - Fix hyphenated words
        - Remove repeated characters
        """
        if not text:
            return ""
            
        # Normalize whitespace
        text = " ".join(text.split())
        
        # Fix hyphenated words that were split across lines
        text = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', text)
        
        # Remove repeated characters (possible OCR errors)
        text = re.sub(r'(.)\1{3,}', r'\1\1', text)
        
        # Fix common OCR errors
        text = re.sub(r'l\s+\.', 'I.', text)  # lowercase L followed by period
        text = re.sub(r'(\d)l', r'\1I', text)  # digit followed by lowercase L
        
        return text

    def _is_header_footer(self, text: str) -> bool:
        """Check if text is likely a header or footer."""
        header_footer_patterns = [
            r'^Page \d+( of \d+)?$',
            r'^\d+$',  # Just a number
            r'^Copyright © \d{4}',
            r'^All rights reserved',
            r'www\..+\.\w+',
            r'http://|https://'
        ]
        
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in header_footer_patterns)

    def _enhance_reference_data(self, ref: ReferenceData) -> None:
        """
        Try to extract more information from raw_text for incomplete references.
        """
        if not ref.raw_text:
            return
            
        # Skip if we already have all important fields
        if ref.authors and ref.title and ref.journal and ref.year:
            return
            
        raw_text = ref.raw_text
        
        # Try to extract year if missing
        if not ref.year:
            year_match = re.search(r'\((\d{4})\)', raw_text)
            if year_match:
                ref.year = year_match.group(1)
        
        # Try to extract authors if missing
        if not ref.authors:
            # Pattern for author list at beginning: "Surname A, Surname B, et al."
            authors_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z](?:\.)?)(?:,\s+[A-Z][a-z]+(?:\s+[A-Z](?:\.)?))*)\.?', raw_text)
            if authors_match:
                author_text = authors_match.group(1)
                # Split into individual authors
                author_parts = re.split(r',\s+(?=\w)', author_text)
                ref.authors = [p.strip() for p in author_parts if p.strip()]
            
            # Try "et al." pattern
            elif et_al_match := re.match(r'^([A-Z][a-z]+(?:\s+[A-Z](?:\.)?)(?:\s+et\s+al\.))\.?', raw_text):
                ref.authors = [et_al_match.group(1)]
        
        # Try to extract title if missing
        if not ref.title and ref.authors:
            # Title typically follows authors and a period
            first_author_pattern = re.escape(ref.authors[0]) if ref.authors else ""
            if first_author_pattern:
                title_match = re.search(f"{first_author_pattern}.*?\\.\s+(.*?)(?:\\.|(?:In:|Journal|Volume))", raw_text, re.DOTALL)
                if title_match:
                    ref.title = title_match.group(1).strip()
        
        # Try to extract journal if missing
        if not ref.journal and ref.title:
            # Journal typically follows title
            title_pattern = re.escape(ref.title) if ref.title else ""
            if title_pattern:
                journal_match = re.search(f"{title_pattern}\.?\s+(.*?)(?:\\.|\d{{4}}|Vol\\.|Volume|\\()", raw_text)
                if journal_match:
                    ref.journal = journal_match.group(1).strip()
        
        # Try to extract volume/issue if missing
        if not ref.volume:
            volume_match = re.search(r'(?:Vol(?:\.|ume)?\s+)?(\d+)(?:\s*\((\d+)\))?', raw_text)
            if volume_match:
                ref.volume = volume_match.group(1)
                if volume_match.group(2) and not ref.issue:
                    ref.issue = volume_match.group(2)
        
        # Try to extract pages if missing
        if not ref.pages:
            pages_match = re.search(r'(?::|,)\s*(?:p(?:p|ages?)?\.?\s*)?(\d+(?:-\d+)?)', raw_text)
            if pages_match:
                ref.pages = pages_match.group(1)
        
        # Try to extract DOI if missing
        if not ref.doi:
            doi_match = re.search(r'(?:doi:?\s*|DOI:?\s*|https?://doi\.org/)(\d{2}\.\d{4}/\S+)', raw_text, re.IGNORECASE)
            if doi_match:
                ref.doi = doi_match.group(1)

    # ----------------------------------------------------------------------
    # Fallback Methods (if GROBID extraction fails)
    # ----------------------------------------------------------------------

    def _extract_sections_from_raw_text(self, text: str) -> List[ProcessedSection]:
        """
        Fallback method to extract sections from raw text if GROBID fails.
        Uses common section headings in academic papers.
        """
        if not text:
            return []
            
        # Common section headings in academic papers with variations
        section_patterns = [
            r'ABSTRACT[:\s]*',
            r'INTRODUCTION[:\s]*',
            r'(?:MATERIALS\s+AND\s+)?METHODS[:\s]*',
            r'RESULTS(?:\s+AND\s+DISCUSSION)?[:\s]*',
            r'DISCUSSION[:\s]*',
            r'CONCLUSION[S]?[:\s]*',
            r'ACKNOWLEDGMENT[S]?[:\s]*',
            r'REFERENCE[S]?[:\s]*',
            r'BIBLIOGRAPHY[:\s]*'
        ]
        
        # Create regex pattern to match all section headings
        pattern = '|'.join(f'({p})' for p in section_patterns)
        section_regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        
        # Find all section matches
        matches = list(section_regex.finditer(text))
        
        # If no sections found, return empty list
        if not matches:
            return []
            
        # Extract sections
        sections = []
        for i, match in enumerate(matches):
            title = match.group(0).strip()
            
            # Get section content (from this match to next match or end)
            start_pos = match.end()
            end_pos = matches[i+1].start() if i < len(matches)-1 else len(text)
            
            section_text = text[start_pos:end_pos].strip()
            paragraphs = self._split_into_paragraphs(section_text)
            
            # Add section if it has content
            if paragraphs:
                sections.append(ProcessedSection(
                    title=title,
                    paragraphs=paragraphs
                ))
                
        return sections

    def _split_into_paragraphs(self, text: str) -> List[str]:
        """Split text into paragraphs based on blank lines."""
        if not text:
            return []
            
        # Split on blank lines
        paragraphs = re.split(r'\n\s*\n', text)
        
        # Clean each paragraph
        cleaned = []
        for p in paragraphs:
            p = p.strip()
            if p:
                # Replace single line breaks with spaces
                p = re.sub(r'\n', ' ', p)
                # Normalize whitespace
                p = re.sub(r'\s+', ' ', p)
                
                cleaned.append(p)
                
        return cleaned

    def _extract_references_from_raw_text(self, text: str) -> List[ReferenceData]:
        """
        Fallback method to extract references from raw text if GROBID fails.
        Looks for REFERENCES or BIBLIOGRAPHY section and parses entries.
        """
        refs = []
        
        # Find references section
        ref_section_match = re.search(
            r'^(REFERENCES|BIBLIOGRAPHY)[:\s]*\n(.*?)(?:^\s*$|$)',
            text,
            re.IGNORECASE | re.MULTILINE | re.DOTALL
        )
        
        if not ref_section_match:
            return refs
            
        ref_text = ref_section_match.group(2)
        
        # Try to split references by common patterns
        # 1. Numbered references: [1], 1., (1), etc.
        numbered_refs = re.split(r'\n\s*(?:\[\d+\]|\d+\.|\(\d+\))\s+', '\n' + ref_text)
        
        if len(numbered_refs) > 1:
            # Remove first empty element
            numbered_refs = numbered_refs[1:]
            
            for i, ref in enumerate(numbered_refs, 1):
                if ref.strip():
                    ref_data = ReferenceData(
                        raw_text=ref.strip(),
                        ref_id=str(i)
                    )
                    # Try to enhance with more metadata
                    self._enhance_reference_data(ref_data)
                    refs.append(ref_data)
        else:
            # 2. Try author-year format
            author_year_refs = re.split(
                r'\n\s*(?:[A-Z][a-z]+(?:,?\s+(?:and|&)\s+[A-Z][a-z]+)?(?:,?\s+et\s+al\.?)?,\s+\d{4})', 
                '\n' + ref_text
            )
            
            if len(author_year_refs) > 1:
                # Remove first empty element
                author_year_refs = author_year_refs[1:]
                
                for i, ref in enumerate(author_year_refs, 1):
                    if ref.strip():
                        ref_data = ReferenceData(
                            raw_text=ref.strip(),
                            ref_id=str(i)
                        )
                        # Try to enhance with more metadata
                        self._enhance_reference_data(ref_data)
                        refs.append(ref_data)
            else:
                # 3. Just split by blank lines as last resort
                blank_line_refs = re.split(r'\n\s*\n', ref_text)
                
                for i, ref in enumerate(blank_line_refs, 1):
                    if ref.strip():
                        ref_data = ReferenceData(
                            raw_text=ref.strip(),
                            ref_id=str(i)
                        )
                        # Try to enhance with more metadata
                        self._enhance_reference_data(ref_data)
                        refs.append(ref_data)
        
        return refs