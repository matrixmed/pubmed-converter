import logging
import os
import requests
import tempfile
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from lxml import etree
import pdfplumber
from io import BytesIO

@dataclass
class ExtractedContent:
    """Container for extracted PDF content."""
    raw_text: str
    pages: List[str] = field(default_factory=list)
    figures: List[Dict[str, Any]] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    # Additional fields for GROBID extraction
    references: List[Dict[str, Any]] = field(default_factory=list)
    authors: List[Dict[str, Any]] = field(default_factory=list)
    title: Optional[str] = None
    abstract: Optional[str] = None
    sections: List[Dict[str, Any]] = field(default_factory=list)
    journal_metadata: Dict[str, Any] = field(default_factory=dict)
    original_pdf_path: Optional[str] = None


class PDFExtractor:
    """
    Enhanced GROBID-based PDF extractor with fallback and merging capabilities.
    Extracts structured content including title, authors, abstract, 
    body sections, and references from academic PDFs.
    """

    def __init__(self, grobid_url: str = "http://localhost:8070", grobid_timeout: int = 120):
        """
        Args:
            grobid_url: Base URL of the GROBID service.
            grobid_timeout: Request timeout in seconds.
        """
        self.grobid_url = grobid_url
        self.grobid_timeout = grobid_timeout
        self._setup_logging()

    def _setup_logging(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            self.logger.addHandler(ch)

    def extract(self, pdf_path: str) -> ExtractedContent:
        """
        Main entry point: Extract text and structure from a PDF using GROBID.
        
        Args:
            pdf_path: Path to the PDF file
        
        Returns:
            ExtractedContent object with structured data
        """
        self.logger.info(f"Extracting PDF with GROBID and enhanced processing: {pdf_path}")

        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            # 1. Extract content using GROBID and fallback methods
            extracted_content = self._extract_with_merge(pdf_path)
            
            # 2. Store the original PDF path for reference
            extracted_content.original_pdf_path = pdf_path
            
            return extracted_content

        except Exception as e:
            self.logger.error(f"Failed to extract PDF content: {e}", exc_info=True)
            # Fallback to basic extraction if GROBID fails
            return self._fallback_extraction(pdf_path)

    def _extract_with_merge(self, pdf_path: str) -> ExtractedContent:
        """
        Enhanced extraction that merges GROBID structured data with fallback
        extraction to ensure completeness.
        """
        # 1. First get fallback extraction (we'll always need this)
        fallback_content = self._fallback_extraction(pdf_path)
        
        # 2. Try GROBID extraction
        tei_xml = self._process_fulltext(pdf_path)
        if not tei_xml:
            self.logger.warning("GROBID extraction failed, using fallback only")
            return fallback_content
        
        # 3. Parse GROBID TEI into structured content
        grobid_content = self._parse_tei(tei_xml)
        
        # 4. Enhance GROBID's header with dedicated header processing if needed
        if not grobid_content.title or not grobid_content.authors:
            self.logger.info("Title or authors missing, trying dedicated header processing")
            self._enhance_with_header_processing(pdf_path, grobid_content)
        
        # 5. Merge GROBID and fallback content to ensure completeness
        merged_content = self._merge_extractions(grobid_content, fallback_content)
        
        # 6. Final post-processing to clean and normalize content
        final_content = self._post_process(merged_content)
        
        return final_content

    def _process_fulltext(self, pdf_path: str) -> Optional[str]:
        """
        Send the PDF to GROBID's /api/processFulltextDocument endpoint.
        Returns the TEI XML as a string.
        """
        url = f"{self.grobid_url}/api/processFulltextDocument"
        
        try:
            with open(pdf_path, 'rb') as pdf_file:
                files = {'input': pdf_file}
                # Enhanced GROBID parameters for better extraction
                data = {
                    'consolidateHeader': '1',       # Add header consolidation
                    'consolidateCitations': '1',    # Enable citation consolidation
                    'includeRawCitations': '1',     # Include raw citation text
                    'includeRawAffiliations': '1',  # Include raw affiliation text
                    'segmentSentences': '1',        # Add sentence segmentation
                    'teiCoordinates': [
                        'persName', 'figure', 'ref', 'biblStruct', 
                        'formula', 'table', 'head'
                    ]
                }

                self.logger.info(f"Sending PDF to GROBID at {url} with enhanced parameters")
                response = requests.post(
                    url,
                    files=files,
                    data=data,
                    timeout=self.grobid_timeout
                )
                
                if response.status_code != 200:
                    self.logger.error(f"GROBID request failed with status {response.status_code}: {response.text}")
                    return None
                    
                # Log the first 500 chars of TEI to aid debugging
                tei_text = response.text
                self.logger.debug(f"Received TEI response (first 500 chars): {tei_text[:500]}...")
                return tei_text
                
        except Exception as e:
            self.logger.error(f"GROBID request failed: {e}", exc_info=True)
            return None

    def _enhance_with_header_processing(self, pdf_path: str, content: ExtractedContent) -> None:
        """
        Enhance extraction with dedicated header processing.
        This can improve title, authors, and affiliations extraction.
        """
        url = f"{self.grobid_url}/api/processHeaderDocument"
        
        try:
            with open(pdf_path, 'rb') as pdf_file:
                files = {'input': pdf_file}
                data = {'consolidateHeader': '1'}
                
                self.logger.info(f"Sending PDF for dedicated header processing")
                response = requests.post(url, files=files, data=data, timeout=self.grobid_timeout)
                
                if response.status_code != 200:
                    self.logger.warning(f"Header processing request failed: {response.status_code}")
                    return
                
                # Parse the header TEI
                header_xml = response.text
                header_root = etree.fromstring(header_xml.encode('utf-8'))
                ns = {'tei': 'http://www.tei-c.org/ns/1.0'}
                
                # Extract title if missing
                if not content.title:
                    title_els = header_root.xpath('.//tei:titleStmt/tei:title/text()', namespaces=ns)
                    if title_els:
                        content.title = title_els[0].strip()
                
                # Extract authors if missing
                if not content.authors:
                    content.authors = self._extract_authors(header_root, ns)
                
        except Exception as e:
            self.logger.error(f"Header processing failed: {e}", exc_info=True)

    def _parse_tei(self, tei_xml: str) -> ExtractedContent:
        """
        Parse TEI XML from GROBID into structured ExtractedContent.
        Enhanced to handle nested divs and capture more text.
        """
        try:
            root = etree.fromstring(tei_xml.encode("utf-8"))
        except Exception as e:
            self.logger.error(f"Failed to parse TEI XML: {e}", exc_info=True)
            return ExtractedContent(raw_text="")

        ns = {'tei': 'http://www.tei-c.org/ns/1.0'}

        # Extract title with fallbacks for different TEI structures
        title = self._extract_title(root, ns)

        # Extract abstract
        abstract = self._extract_abstract(root, ns)

        # Extract journal metadata
        journal_metadata = self._extract_journal_metadata(root, ns)
        
        # Force JCAD journal information regardless of extraction
        journal_metadata['journal_id'] = 'JCAD'
        journal_metadata['journal_title'] = 'The Journal of Clinical and Aesthetic Dermatology'
        journal_metadata['issn'] = '1941-2789'
        journal_metadata['publisher'] = 'Matrix Medical Communications'

        # Extract authors with affiliations
        authors = self._extract_authors(root, ns)

        # Extract body text as sections - improved to handle nested divs
        sections = self._extract_sections(root, ns)
        
        # Combine all section texts for raw_text
        all_paragraphs = []
        for section in sections:
            if 'title' in section and section['title']:
                all_paragraphs.append(section['title'])
            for p in section.get('paragraphs', []):
                all_paragraphs.append(p)
        
        raw_text = "\n\n".join(all_paragraphs)

        # Extract references
        references = self._extract_references(root, ns)

        # Extract figures if available
        figures = self._extract_figures(root, ns)
        
        # Extract tables if available
        tables = self._extract_tables(root, ns)

        # Create ExtractedContent
        extracted = ExtractedContent(
            raw_text=raw_text,
            pages=[raw_text],  # Will be replaced with actual pages later
            figures=figures,
            tables=tables,
            references=references,
            authors=authors,
            title=title,
            abstract=abstract,
            sections=sections,
            journal_metadata=journal_metadata
        )

        return extracted

    def _extract_title(self, root, ns) -> Optional[str]:
        """Extract title with multiple fallback strategies"""
        # Try different XPaths for title
        title_paths = [
            './/tei:titleStmt/tei:title/text()',
            './/tei:sourceDesc//tei:title[@type="main"]/text()',
            './/tei:titlePage//tei:docTitle//text()',
            './/tei:front//tei:docTitle//text()'
        ]
        
        for path in title_paths:
            title_els = root.xpath(path, namespaces=ns)
            if title_els:
                title_text = " ".join([t.strip() for t in title_els if t.strip()])
                if title_text:
                    # Clean up title - remove line breaks, extra spaces
                    title_text = re.sub(r'\s+', ' ', title_text).strip()
                    return title_text
        
        # Look for title in first heading of body
        first_head = root.xpath('.//tei:body//tei:head[1]//text()', namespaces=ns)
        if first_head:
            title_text = " ".join([t.strip() for t in first_head if t.strip()])
            return title_text
            
        return None

    def _extract_abstract(self, root, ns) -> Optional[str]:
        """Extract abstract with better text handling"""
        # Find abstract div or section
        abstract_els = root.xpath('.//tei:profileDesc/tei:abstract//text()', namespaces=ns)
        
        if abstract_els:
            # Join all text, normalize whitespace
            abstract_text = " ".join([t.strip() for t in abstract_els if t.strip()])
            abstract_text = re.sub(r'\s+', ' ', abstract_text).strip()
            
            # If abstract is very long, it might include non-abstract content
            # Limit to reasonable length (e.g., 1000 chars)
            if len(abstract_text) > 1000:
                sentences = re.split(r'(?<=[.!?])\s+', abstract_text)
                if len(sentences) > 5:
                    # Take first 5 sentences or first 1000 chars, whichever is shorter
                    abstract_text = " ".join(sentences[:5])
                    if len(abstract_text) > 1000:
                        abstract_text = abstract_text[:997] + "..."
            
            return abstract_text
        
        # Try alternate abstract locations
        alt_abstract = root.xpath('.//tei:div[@type="abstract"]//text()', namespaces=ns)
        if alt_abstract:
            abstract_text = " ".join([t.strip() for t in alt_abstract if t.strip()])
            return re.sub(r'\s+', ' ', abstract_text).strip()
            
        return None

    def _extract_journal_metadata(self, root, ns) -> Dict[str, Any]:
        """Extract journal metadata from TEI with improved paths"""
        metadata = {}
        
        # Always set JCAD information
        metadata['journal_id'] = 'JCAD'
        metadata['journal_title'] = 'The Journal of Clinical and Aesthetic Dermatology'
        metadata['issn'] = '1941-2789'
        metadata['publisher'] = 'Matrix Medical Communications'
        
        # Extract volume, issue, pages if available
        volume = root.xpath('.//tei:sourceDesc//tei:biblScope[@unit="volume"]/text()', namespaces=ns)
        if volume:
            metadata['volume'] = volume[0].strip()
            
        issue = root.xpath('.//tei:sourceDesc//tei:biblScope[@unit="issue"]/text()', namespaces=ns)
        if issue:
            metadata['issue'] = issue[0].strip()
            
        fpage = root.xpath('.//tei:sourceDesc//tei:biblScope[@unit="page"]/@from', namespaces=ns)
        if fpage:
            metadata['fpage'] = fpage[0].strip()
            
        lpage = root.xpath('.//tei:sourceDesc//tei:biblScope[@unit="page"]/@to', namespaces=ns)
        if lpage:
            metadata['lpage'] = lpage[0].strip()
        
        # Publication date
        pub_date = {}
        year = root.xpath('.//tei:sourceDesc//tei:date/@when | .//tei:sourceDesc//tei:date/text()', namespaces=ns)
        if year:
            year_text = year[0].strip()
            # Extract year from date format (e.g., 2024-01-15)
            year_match = re.search(r'(\d{4})', year_text)
            if year_match:
                pub_date['year'] = year_match.group(1)
                
                # Try to extract month if available
                month_match = re.search(r'\d{4}-(\d{2})', year_text)
                if month_match:
                    pub_date['month'] = month_match.group(1)
                
        if pub_date:
            metadata['pub_date'] = pub_date
        
        return metadata

    def _extract_authors(self, root, ns) -> List[Dict[str, Any]]:
        """Extract author information with affiliations - improved with better paths"""
        authors = []
        
        # Find all author nodes - multiple paths for robustness
        author_paths = [
            './/tei:sourceDesc//tei:analytic/tei:author',
            './/tei:fileDesc//tei:author',
            './/tei:teiHeader//tei:author'
        ]
        
        author_nodes = []
        for path in author_paths:
            nodes = root.xpath(path, namespaces=ns)
            if nodes:
                author_nodes.extend(nodes)
                break  # Use first successful path
        
        # Get all affiliations to reference later
        all_affiliations = {}
        affiliation_nodes = root.xpath('.//tei:teiHeader//tei:affiliation', namespaces=ns)
        for aff in affiliation_nodes:
            aff_id = aff.get('{http://www.w3.org/XML/1998/namespace}id')
            if aff_id:
                aff_text = " ".join(aff.xpath('.//text()'))
                all_affiliations[aff_id] = aff_text.strip()
        
        for i, author_node in enumerate(author_nodes):
            author_data = {
                'surname': '',
                'given_names': '',
                'affiliations': [],
                'is_corresponding': False
            }
            
            # Get name components
            pers_name = author_node.find('.//tei:persName', namespaces=ns)
            if pers_name is not None:
                surname = pers_name.findtext('tei:surname', default="", namespaces=ns)
                forename = pers_name.findtext('tei:forename', default="", namespaces=ns)
                
                author_data['surname'] = surname.strip()
                author_data['given_names'] = forename.strip()
                
                # Check for possible middle names in additional forenames
                middle_names = pers_name.xpath('.//tei:forename[@type="middle"]/text()', namespaces=ns)
                if middle_names:
                    author_data['given_names'] += " " + " ".join([m.strip() for m in middle_names])
            else:
                # If no structured name, try to get raw author name
                raw_name = author_node.xpath('.//text()')
                if raw_name:
                    name_text = " ".join([t.strip() for t in raw_name if t.strip()])
                    name_parts = name_text.split(',', 1)
                    if len(name_parts) == 2:
                        author_data['surname'] = name_parts[0].strip()
                        author_data['given_names'] = name_parts[1].strip()
                    else:
                        words = name_text.split()
                        if len(words) > 1:
                            author_data['surname'] = words[-1]
                            author_data['given_names'] = " ".join(words[:-1])
                        else:
                            author_data['surname'] = name_text
            
            # Get affiliations
            affiliations = []
            
            # Method 1: Direct affiliation nodes
            aff_nodes = author_node.xpath('.//tei:affiliation', namespaces=ns)
            for aff in aff_nodes:
                aff_text = " ".join(aff.xpath('.//text()'))
                if aff_text.strip():
                    affiliations.append(aff_text.strip())
            
            # Method 2: Affiliation references
            aff_refs = author_node.xpath('.//tei:affiliation/@key', namespaces=ns)
            for ref in aff_refs:
                if ref in all_affiliations:
                    affiliations.append(all_affiliations[ref])
            
            # Get email if available
            email = author_node.xpath('.//tei:email/text()', namespaces=ns)
            if email:
                author_data['email'] = email[0].strip()
            
            # Check if this is corresponding author
            is_corresp = author_node.get('role') == 'corresp'
            author_data['is_corresponding'] = is_corresp
            
            # Add affiliations to author data
            author_data['affiliations'] = affiliations
            
            # Add author if we have at least surname
            if author_data.get('surname'):
                authors.append(author_data)
        
        return authors

    def _extract_sections(self, root, ns) -> List[Dict[str, Any]]:
        """
        Extract body text as structured sections.
        Improved to handle nested divs, multiple section types.
        """
        sections = []
        
        # Find all body divisions (sections) - handle nested divs
        div_nodes = root.xpath('.//tei:body//tei:div', namespaces=ns)
        
        # If no divs found, try other containers
        if not div_nodes:
            div_nodes = root.xpath('.//tei:body//tei:p', namespaces=ns)
            if div_nodes:
                # Create a single section with all paragraphs
                paragraphs = []
                for p in div_nodes:
                    p_text = " ".join(p.xpath('.//text()'))
                    p_text = re.sub(r'\s+', ' ', p_text).strip()
                    if p_text:
                        paragraphs.append(p_text)
                
                if paragraphs:
                    sections.append({
                        'title': '',
                        'paragraphs': paragraphs
                    })
                return sections
        
        # Process each div as a section
        processed_divs = set()  # Track processed divs to avoid duplicates
        
        for div in div_nodes:
            # Skip if already processed (can happen with nested divs)
            div_id = div.get('{http://www.w3.org/XML/1998/namespace}id', '')
            if div_id in processed_divs:
                continue
                
            processed_divs.add(div_id)
            
            section = {}
            
            # Extract section title/heading
            head = div.find('.//tei:head', namespaces=ns)
            if head is not None:
                section['title'] = " ".join(head.xpath('.//text()')).strip()
                section['title'] = re.sub(r'\s+', ' ', section['title'])
            else:
                section['title'] = ""
            
            # Extract paragraphs directly under this div (not in nested divs)
            paragraphs = []
            p_nodes = div.xpath('./tei:p', namespaces=ns)
            
            for p in p_nodes:
                # Get all text, including text inside formula, ref, etc.
                p_text = " ".join(p.xpath('.//text()'))
                p_text = re.sub(r'\s+', ' ', p_text).strip()
                
                if p_text:
                    paragraphs.append(p_text)
            
            section['paragraphs'] = paragraphs
            
            # Add section if it has content
            if section['title'] or paragraphs:
                sections.append(section)
        
        # If no structured sections were found, create a single section with all paragraphs
        if not sections:
            all_paragraphs = []
            p_nodes = root.xpath('.//tei:body//tei:p', namespaces=ns)
            
            for p in p_nodes:
                p_text = " ".join(p.xpath('.//text()')).strip()
                p_text = re.sub(r'\s+', ' ', p_text)
                if p_text:
                    all_paragraphs.append(p_text)
            
            if all_paragraphs:
                sections.append({
                    'title': "BODY",
                    'paragraphs': all_paragraphs
                })
        
        # Detect section boundaries from all text if sections look incomplete
        body_text = " ".join(root.xpath('.//tei:body//text()', namespaces=ns))
        if body_text and not sections:
            sections = self._extract_sections_from_text(body_text)
                
        return sections

    def _extract_sections_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Fallback method to extract sections from raw text"""
        sections = []
        
        # Common section headings in academic papers
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
        
        # Create regex pattern to find all section headings
        pattern = '|'.join(f'({p})' for p in section_patterns)
        section_regex = re.compile(pattern, re.IGNORECASE)
        
        # Find all section matches
        matches = list(section_regex.finditer(text))
        
        # If no sections found, return text as one section
        if not matches:
            return [{
                'title': '',
                'paragraphs': [text.strip()]
            }]
            
        # Extract each section
        for i, match in enumerate(matches):
            title = match.group(0).strip()
            
            # Get section content (from this match to next match or end)
            start_pos = match.end()
            end_pos = matches[i+1].start() if i < len(matches)-1 else len(text)
            
            section_text = text[start_pos:end_pos].strip()
            
            # Split into paragraphs
            paragraphs = re.split(r'\n\s*\n', section_text)
            paragraphs = [p.strip() for p in paragraphs if p.strip()]
            
            # Add section
            sections.append({
                'title': title,
                'paragraphs': paragraphs
            })
            
        return sections

    def _extract_references(self, root, ns) -> List[Dict[str, Any]]:
        """Extract references from TEI with improved parsing"""
        references = []
        
        # Find all reference nodes
        ref_nodes = root.xpath('.//tei:listBibl/tei:biblStruct', namespaces=ns)
        
        # If no structured references, try to find raw reference list
        if not ref_nodes:
            ref_div = root.xpath('.//tei:div[@type="references" or @type="bibliography"]', namespaces=ns)
            if ref_div:
                return self._extract_references_from_div(ref_div[0], ns)
        
        for i, ref in enumerate(ref_nodes, 1):
            ref_data = {'ref_id': str(i)}
            
            # Get raw text for full reference
            ref_text = " ".join(ref.xpath('.//text()')).strip()
            ref_text = re.sub(r'\s+', ' ', ref_text)  # Normalize whitespace
            ref_data['raw_text'] = ref_text
            
            # Get authors
            authors = []
            author_nodes = ref.xpath('.//tei:author/tei:persName', namespaces=ns)
            
            for author in author_nodes:
                surname = author.findtext('.//tei:surname', default="", namespaces=ns).strip()
                forename = author.findtext('.//tei:forename', default="", namespaces=ns).strip()
                
                if surname or forename:
                    authors.append(f"{surname}, {forename}")
            
            ref_data['authors'] = authors
            
            # Get year
            year = ref.xpath('.//tei:date/@when', namespaces=ns)
            if not year:
                year = ref.xpath('.//tei:date/text()', namespaces=ns)
            
            if year:
                year_text = year[0].strip()
                # Extract year from date format
                year_match = re.search(r'(\d{4})', year_text)
                if year_match:
                    ref_data['year'] = year_match.group(1)
            
            # Get title
            title = ref.xpath('.//tei:analytic/tei:title/text()', namespaces=ns)
            if title:
                ref_data['title'] = title[0].strip()
            
            # Get journal/source
            journal = ref.xpath('.//tei:monogr/tei:title[@level="j"]/text()', namespaces=ns)
            if journal:
                ref_data['journal'] = journal[0].strip()
            
            # Get volume, issue, pages
            volume = ref.xpath('.//tei:biblScope[@unit="volume"]/text()', namespaces=ns)
            if volume:
                ref_data['volume'] = volume[0].strip()
                
            issue = ref.xpath('.//tei:biblScope[@unit="issue"]/text()', namespaces=ns)
            if issue:
                ref_data['issue'] = issue[0].strip()
                
            pages = ref.xpath('.//tei:biblScope[@unit="page"]/text()', namespaces=ns)
            if pages:
                ref_data['pages'] = pages[0].strip()
            
            # Get DOI
            doi = ref.xpath('.//tei:idno[@type="DOI"]/text()', namespaces=ns)
            if doi:
                ref_data['doi'] = doi[0].strip()
            
            references.append(ref_data)
            
        return references

    def _extract_references_from_div(self, ref_div, ns) -> List[Dict[str, Any]]:
        """Extract references from a references div when no structured biblStruct exists"""
        references = []
        
        # Try to find reference items
        ref_items = ref_div.xpath('.//tei:p | .//tei:item', namespaces=ns)
        
        if ref_items:
            for i, item in enumerate(ref_items, 1):
                ref_text = " ".join(item.xpath('.//text()')).strip()
                ref_text = re.sub(r'\s+', ' ', ref_text)
                
                if ref_text:
                    # Try to parse basic information
                    ref_data = self._parse_reference_text(ref_text, i)
                    references.append(ref_data)
        else:
            # No items found, try to split text by common patterns
            text = " ".join(ref_div.xpath('.//text()')).strip()
            
            # Try different splitting patterns
            # 1. Numbered refs: [1], 1., (1)
            ref_matches = re.split(r'\s*(?:\[\d+\]|\d+\.|\(\d+\))\s+', '\n' + text)
            
            if len(ref_matches) > 2:  # First element is empty due to \n
                for i, ref_text in enumerate(ref_matches[1:], 1):
                    if ref_text.strip():
                        ref_data = self._parse_reference_text(ref_text.strip(), i)
                        references.append(ref_data)
        
        return references

    def _parse_reference_text(self, text: str, ref_id: int) -> Dict[str, Any]:
        """Parse a reference text string into structured data"""
        ref_data = {
            'ref_id': str(ref_id),
            'raw_text': text
        }
        
        # Try to extract authors
        # Pattern: Surname A, Surname B, et al.
        authors_match = re.match(r'^([A-Z][a-z]+\s+[A-Z](?:\s*,\s*[A-Z][a-z]+\s+[A-Z])*(?:\s*,\s*et al\.)?)', text)
        if authors_match:
            author_text = authors_match.group(1)
            ref_data['authors'] = [author_text]
        
        # Try to extract year
        year_match = re.search(r'\((\d{4})\)', text)
        if year_match:
            ref_data['year'] = year_match.group(1)
        
        # Try to extract journal and volume/issue
        journal_match = re.search(r'([A-Z][A-Za-z\s]+)\.\s+(?:Vol\.?\s*)?(\d+)(?:\((\d+)\))?', text)
        if journal_match:
            ref_data['journal'] = journal_match.group(1)
            ref_data['volume'] = journal_match.group(2)
            if journal_match.group(3):
                ref_data['issue'] = journal_match.group(3)
        
        # Try to extract pages
        pages_match = re.search(r'(?::|,)\s*(?:pp?\.)?\s*(\d+(?:-\d+)?)', text)
        if pages_match:
            ref_data['pages'] = pages_match.group(1)
        
        # Try to extract DOI
        doi_match = re.search(r'doi:?\s*(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)', text, re.IGNORECASE)
        if doi_match:
            ref_data['doi'] = doi_match.group(1)
        
        return ref_data

    def _extract_figures(self, root, ns) -> List[Dict[str, Any]]:
        """Extract figures from TEI"""
        figures = []
        
        # Find all figure nodes
        figure_nodes = root.xpath('.//tei:figure', namespaces=ns)
        
        for i, fig in enumerate(figure_nodes, 1):
            figure_data = {'id': f"fig{i}"}
            
            # Extract figure label/number
            label = fig.findtext('.//tei:head', default="", namespaces=ns)
            if label:
                figure_data['label'] = label.strip()
            
            # Extract figure caption
            caption_parts = []
            for desc in fig.xpath('.//tei:figDesc//text()', namespaces=ns):
                if desc.strip():
                    caption_parts.append(desc.strip())
            
            if caption_parts:
                figure_data['caption'] = " ".join(caption_parts)
            
            # If we have caption or label, add the figure
            if 'caption' in figure_data or 'label' in figure_data:
                figures.append(figure_data)
        
        return figures

    def _extract_tables(self, root, ns) -> List[Dict[str, Any]]:
        """Extract tables from TEI"""
        tables = []
        
        # Find all table nodes
        table_nodes = root.xpath('.//tei:table', namespaces=ns)
        
        for i, table in enumerate(table_nodes, 1):
            table_data = {'id': f"table{i}"}
            
            # Extract table title/caption
            # Try preceding head element first
            caption = table.xpath('preceding::tei:head[1]/text()', namespaces=ns)
            if caption:
                table_data['caption'] = caption[0].strip()
            else:
                # Try parent div's head
                parent_div = table.xpath('./parent::tei:div', namespaces=ns)
                if parent_div:
                    caption = parent_div[0].xpath('./tei:head/text()', namespaces=ns)
                    if caption:
                        table_data['caption'] = caption[0].strip()
            
            # Extract rows/content as simplified text
            rows = []
            for row in table.xpath('.//tei:row', namespaces=ns):
                cells = []
                for cell in row.xpath('.//tei:cell//text()', namespaces=ns):
                    if cell.strip():
                        cells.append(cell.strip())
                
                if cells:
                    rows.append(" | ".join(cells))
            
            if rows:
                table_data['content'] = "\n".join(rows)
                tables.append(table_data)
        
        return tables
        
    def _merge_extractions(self, grobid_content: ExtractedContent, fallback_content: ExtractedContent) -> ExtractedContent:
        """
        Merge GROBID extraction with fallback extraction to ensure completeness.
        Prioritize GROBID structure but use fallback text when GROBID text is missing.
        """
        # Start with GROBID content as the base
        merged = grobid_content
        
        # Keep the raw fallback content in case we need it
        merged.pages = fallback_content.pages
        
        # 1. If GROBID didn't find a title, use the fallback's first text as possible title
        if not merged.title and fallback_content.raw_text:
            # Take first non-empty line as potential title
            first_line = next(
                (line for line in fallback_content.raw_text.splitlines() if line.strip()),
                ""
            )
            if len(first_line) > 10 and len(first_line) < 200:  # Reasonable title length
                merged.title = first_line.strip()
        
        # 2. If GROBID has no or very little raw text, use fallback's raw text
        if not merged.raw_text or len(merged.raw_text) < 100:
            merged.raw_text = fallback_content.raw_text
        
        # 3. If GROBID has no or very few sections, try to extract from fallback
        if not merged.sections or sum(len(s.get('paragraphs', [])) for s in merged.sections) < 3:
            # Try to extract sections from fallback text
            if fallback_content.raw_text:
                merged.sections = self._extract_sections_from_text(fallback_content.raw_text)
        
        # 4. Enrich sections with fallback text if they seem incomplete
        else:
            # Get all fallback paragraphs
            fallback_paragraphs = []
            if fallback_content.raw_text:
                fallback_paragraphs = re.split(r'\n\s*\n', fallback_content.raw_text)
                fallback_paragraphs = [p.strip() for p in fallback_paragraphs if p.strip()]
            
            # Check each section for completeness
            for i, section in enumerate(merged.sections):
                paragraphs = section.get('paragraphs', [])
                
                # If section has no paragraphs but has a title, try to find content in fallback
                if section.get('title') and not paragraphs:
                    title = section['title'].lower()
                    
                    # Find matching paragraph in fallback that might contain this section
                    for j, fb_para in enumerate(fallback_paragraphs):
                        if title in fb_para.lower():
                            # Take this and next paragraph as content
                            if j + 1 < len(fallback_paragraphs):
                                section['paragraphs'] = [fallback_paragraphs[j+1]]
                            break
                
                # If section has very short paragraphs, might be incomplete
                elif paragraphs and all(len(p) < 100 for p in paragraphs):
                    # Try to find matching content in fallback
                    # Use simple text matching - look for the first paragraph in fallback
                    if paragraphs[0] and fallback_content.raw_text:
                        first_para = paragraphs[0]
                        for para in fallback_paragraphs:
                            # If fallback paragraph contains this text but is longer
                            if first_para in para and len(para) > len(first_para) * 1.5:
                                section['paragraphs'] = [para]
                                break
        
        # 5. If no references found, try to extract from fallback
        if not merged.references and fallback_content.raw_text:
            ref_section_match = re.search(
                r'^(?:REFERENCES|BIBLIOGRAPHY)[:\s]*\n(.*?)(?:\n\s*\n|$)',
                fallback_content.raw_text,
                re.IGNORECASE | re.MULTILINE | re.DOTALL
            )
            
            if ref_section_match:
                ref_text = ref_section_match.group(1)
                # Split by likely reference patterns
                refs = re.split(r'\n\s*(?:\[\d+\]|\d+\.|\(\d+\))\s+', '\n' + ref_text)
                
                for i, ref in enumerate(refs[1:], 1):  # Skip first empty element
                    if ref.strip():
                        merged.references.append({
                            'ref_id': str(i),
                            'raw_text': ref.strip()
                        })
        
        return merged
    
    def _post_process(self, content: ExtractedContent) -> ExtractedContent:
        """
        Final post-processing to clean up merged content:
        - Remove duplicate paragraphs
        - Fix common OCR issues
        - Remove page numbers and headers/footers
        - Ensure standard JCAD journal info
        """
        # 1. Ensure journal metadata is JCAD regardless of input
        content.journal_metadata = {
            'journal_id': 'JCAD',
            'journal_title': 'The Journal of Clinical and Aesthetic Dermatology',
            'issn': '1941-2789',
            'publisher': 'Matrix Medical Communications'
        }
        
        # 2. Ensure title is properly formatted
        if content.title:
            # Normalize whitespace
            content.title = re.sub(r'\s+', ' ', content.title).strip()
            
            # Title case if all uppercase or all lowercase
            if content.title.isupper() or content.title.islower():
                content.title = content.title.title()
        
        # 3. Clean each section's paragraphs
        for section in content.sections:
            paragraphs = section.get('paragraphs', [])
            cleaned_paragraphs = []
            seen_paragraphs = set()
            
            for p in paragraphs:
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
                
                # Skip if we've seen this paragraph before
                if p in seen_paragraphs:
                    continue
                
                seen_paragraphs.add(p)
                cleaned_paragraphs.append(p)
            
            section['paragraphs'] = cleaned_paragraphs
        
        # 4. Rebuild raw_text from cleaned sections
        all_paragraphs = []
        for section in content.sections:
            if 'title' in section and section['title']:
                all_paragraphs.append(section['title'])
            for p in section.get('paragraphs', []):
                all_paragraphs.append(p)
        
        if all_paragraphs:
            content.raw_text = "\n\n".join(all_paragraphs)
        
        # 5. Clean references
        self._clean_references(content.references)
        
        return content
    
    def _clean_paragraph(self, text: str) -> str:
        """Clean a paragraph by normalizing whitespace and fixing common issues."""
        # Normalize whitespace
        text = " ".join(text.split())
        
        # Fix hyphenated words that were split across lines
        text = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', text)
        
        # Remove repeated characters (possible OCR errors)
        text = re.sub(r'(.)\1{3,}', r'\1', text)
        
        return text
    
    def _is_header_footer(self, text: str) -> bool:
        """Check if text is likely a header or footer."""
        header_footer_patterns = [
            r'^Page \d+( of \d+)?$',
            r'^\d+$',
            r'^Copyright © \d{4}',
            r'^All rights reserved',
            r'www\..+\.\w+',
            r'http://|https://'
        ]
        
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in header_footer_patterns)
    
    def _clean_references(self, references: List[Dict[str, Any]]) -> None:
        """Clean reference data"""
        for ref in references:
            if 'raw_text' in ref:
                # Normalize whitespace
                ref['raw_text'] = re.sub(r'\s+', ' ', ref['raw_text']).strip()
                
                # Ensure ref_id is present
                if 'ref_id' not in ref or not ref['ref_id']:
                    ref['ref_id'] = str(references.index(ref) + 1)

    def _fallback_extraction(self, pdf_path: str) -> ExtractedContent:
        """
        Fallback extraction using pdfplumber to get basic text.
        Used when GROBID fails or as a complement to GROBID.
        """
        self.logger.info("Using fallback extraction with pdfplumber")
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages = []
                raw_text = ""
                
                # Extract text from each page
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    if text.strip():
                        pages.append(text)
                        raw_text += text + "\n\n"
                
                # Try to identify title from first page
                title = None
                if pages:
                    first_page = pages[0]
                    lines = first_page.splitlines()
                    for line in lines[:10]:  # Look at first 10 lines
                        line = line.strip()
                        if line and 10 < len(line) < 150 and not line.startswith('Page'):
                            title = line
                            break
                
                # Try to identify sections
                sections = self._extract_sections_from_text(raw_text)
                
                return ExtractedContent(
                    raw_text=raw_text,
                    pages=pages,
                    title=title,
                    sections=sections
                )
        except Exception as e:
            self.logger.error(f"pdfplumber fallback failed: {e}", exc_info=True)
            # Last resort: Return empty content
            return ExtractedContent(raw_text="", pages=[])