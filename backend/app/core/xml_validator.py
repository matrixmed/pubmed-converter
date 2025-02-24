import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
import re
from lxml import etree
import os

@dataclass
class ValidationError:
    """Structured validation error."""
    element: str
    message: str
    severity: str
    line_number: Optional[int] = None
    context: Optional[str] = None
    suggestion: Optional[str] = None

@dataclass
class ValidationResult:
    """Validation result container."""
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

class XMLValidator:
    """PubMed DTD 2.3 XML validator with enhanced error reporting."""

    def __init__(self, dtd_path: Optional[str] = None):
        """Initialize validator with DTD path."""
        self.base_dir = Path(__file__).parent.parent.parent
        self.dtd_path = dtd_path or str(self.base_dir / "config" / "nlm-dtd-2.3" / "journalpublishing.dtd")
        self._setup_logging()
        self._setup_validation_rules()

    def _setup_logging(self) -> None:
        """Configure logging system."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            # Console handler
            console_handler = logging.StreamHandler()
            console_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)

            # File handler
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            file_handler = logging.FileHandler(
                log_dir / f"xml_validation_{datetime.now().strftime('%Y%m%d')}.log"
            )
            file_handler.setFormatter(console_formatter)
            self.logger.addHandler(file_handler)

    def _setup_validation_rules(self) -> None:
        """Setup PubMed-specific validation rules."""
        # Critical required elements
        self.required_elements = {
            'front/journal-meta/journal-id': 'Journal ID is required',
            'front/journal-meta/journal-title-group/journal-title': 'Journal title is required',
            'front/article-meta/article-id': 'Article ID is required',
            'front/article-meta/title-group/article-title': 'Article title is required',
            'front/article-meta/contrib-group/contrib': 'At least one author is required',
            'front/article-meta/pub-date': 'Publication date is required'
        }
        
        # Optional but recommended elements
        self.recommended_elements = {
            'front/article-meta/abstract': 'Abstract is recommended',
            'back/ref-list': 'References section is recommended',
            'front/article-meta/volume': 'Volume information is recommended',
            'front/article-meta/issue': 'Issue information is recommended',
            'front/article-meta/fpage': 'First page information is recommended'
        }

        # Allowed values for specific attributes
        self.allowed_values = {
            'article/@article-type': [
                'research-article', 'review-article', 'case-report',
                'letter', 'editorial', 'abstract', 'review',
                'brief-report', 'correction', 'retraction'
            ],
            'journal-id/@journal-id-type': [
                'publisher-id', 'nlm-ta', 'doi', 'hwp', 'pmc'
            ]
        }

    def validate(self, xml_content: str) -> ValidationResult:
        """Validate XML against PubMed rules and DTD."""
        validation_errors = []
        validation_warnings = []
        
        try:
            # Parse XML
            parser = self._create_parser()
            root = etree.fromstring(xml_content.encode('utf-8'), parser)
            
            # 1. DTD Validation
            self._validate_against_dtd(root, validation_errors)
            
            # 2. PubMed-specific requirements
            self._check_required_elements(root, validation_errors, validation_warnings)
            self._check_attribute_values(root, validation_errors)
            self._check_author_content(root, validation_errors, validation_warnings)
            self._check_references(root, validation_errors, validation_warnings)
            
            is_valid = len(validation_errors) == 0
            return ValidationResult(
                is_valid=is_valid, 
                errors=validation_errors,
                warnings=validation_warnings
            )
            
        except Exception as e:
            self.logger.error(f"Validation error: {str(e)}", exc_info=True)
            validation_errors.append(
                ValidationError(
                    element="xml",
                    message=str(e),
                    severity="error",
                    suggestion="Check XML structure and encoding"
                )
            )
            return ValidationResult(is_valid=False, errors=validation_errors)

    def _check_required_elements(self, root: etree.Element, errors: List[ValidationError], warnings: List[ValidationError]):
        """Check presence of critical PubMed elements."""
        # Check required elements
        for xpath, message in self.required_elements.items():
            if not root.findall(f".//{xpath.replace('/', '/')}"):
                errors.append(ValidationError(
                    element=xpath.split('/')[-1],
                    message=message,
                    severity="error",
                    suggestion="Add missing required element"
                ))
        
        # Check recommended elements
        for xpath, message in self.recommended_elements.items():
            if not root.findall(f".//{xpath.replace('/', '/')}"):
                warnings.append(ValidationError(
                    element=xpath.split('/')[-1],
                    message=message,
                    severity="warning",
                    suggestion="Consider adding this element for completeness"
                ))

    def _check_attribute_values(self, root: etree.Element, errors: List[ValidationError]):
        """Check attribute values against allowed lists."""
        for xpath, allowed in self.allowed_values.items():
            # Split into element and attribute
            parts = xpath.split('/@')
            if len(parts) != 2:
                continue
                
            element_path, attr_name = parts
                
            # Find elements
            elements = root.findall(f".//{element_path.replace('/', '/')}")
            for element in elements:
                value = element.get(attr_name)
                if value and value not in allowed:
                    errors.append(ValidationError(
                        element=element_path.split('/')[-1],
                        message=f"Invalid value '{value}' for attribute {attr_name}",
                        severity="error",
                        suggestion=f"Allowed values: {', '.join(allowed)}"
                    ))

    def _check_author_content(self, root: etree.Element, errors: List[ValidationError], warnings: List[ValidationError]):
        """Validate author information."""
        for i, contrib in enumerate(root.findall(".//contrib[@contrib-type='author']"), 1):
            # Check for name components
            name = contrib.find(".//name")
            if name is not None:
                if not name.find(".//surname"):
                    errors.append(ValidationError(
                        element="author",
                        message=f"Author {i} missing surname",
                        severity="error",
                        suggestion="Add surname for each author"
                    ))
                if not name.find(".//given-names"):
                    warnings.append(ValidationError(
                        element="author",
                        message=f"Author {i} missing given names",
                        severity="warning",
                        suggestion="Add given names for each author"
                    ))
            
            # Check if corresponding author has an email or xref
            if contrib.get("corresp") == "yes":
                if not contrib.find(".//email") and not contrib.find(".//xref[@ref-type='corresp']"):
                    warnings.append(ValidationError(
                        element="author",
                        message=f"Corresponding author {i} should have email or correspondence note",
                        severity="warning",
                        suggestion="Add email or correspondence reference to corresponding author"
                    ))
            
            # Check if author has affiliation or xref to affiliation
            if not contrib.find(".//aff") and not contrib.find(".//xref[@ref-type='aff']"):
                warnings.append(ValidationError(
                    element="author",
                    message=f"Author {i} should have affiliation information",
                    severity="warning",
                    suggestion="Add affiliation or reference to affiliation for each author"
                ))

    def _check_references(self, root: etree.Element, errors: List[ValidationError], warnings: List[ValidationError]):
        """Validate reference formatting."""
        refs = root.findall(".//ref")
        
        if refs:
            for i, ref in enumerate(refs, 1):
                # Check if reference has ID
                if not ref.get('id'):
                    errors.append(ValidationError(
                        element="reference",
                        message=f"Reference {i} missing ID attribute",
                        severity="error",
                        suggestion="Add unique identifier to each reference (format: R1, R2, etc.)"
                    ))
                
                # Check if reference has citation content
                if not (ref.find(".//mixed-citation") or ref.find(".//element-citation")):
                    errors.append(ValidationError(
                        element="reference",
                        message=f"Reference {i} missing citation content",
                        severity="error",
                        suggestion="Add citation details in mixed-citation or element-citation"
                    ))
                
                # Check content of mixed-citation
                mixed_citation = ref.find(".//mixed-citation")
                if mixed_citation is not None:
                    # Check if publication-type is set
                    if not mixed_citation.get("publication-type"):
                        warnings.append(ValidationError(
                            element="reference",
                            message=f"Reference {i} missing publication-type",
                            severity="warning",
                            suggestion="Add publication-type attribute (e.g., journal, book, etc.)"
                        ))
                    
                    # Check if citation has any content
                    if not (mixed_citation.text or len(mixed_citation) > 0):
                        errors.append(ValidationError(
                            element="reference",
                            message=f"Reference {i} has empty citation",
                            severity="error",
                            suggestion="Add citation text or structured elements"
                        ))

    def _create_parser(self) -> etree.XMLParser:
        """Create XML parser with custom entity resolver."""
        class DTDResolver(etree.Resolver):
            def __init__(self, dtd_base_path: str):
                self.dtd_base_path = Path(dtd_base_path).parent
                super().__init__()

            def resolve(self, system_url, public_id, context):
                # Handle both relative and absolute paths
                if system_url and system_url.startswith('file:/'):
                    system_url = system_url.split('file:/')[-1]
                
                # Try multiple path resolutions
                try_paths = [
                    Path(system_url),
                    self.dtd_base_path / Path(system_url).name,
                    self.dtd_base_path / system_url
                ]
                
                for path in try_paths:
                    if path.exists():
                        return self.resolve_filename(str(path), context)
                
                # If we get here, we couldn't resolve the entity
                self.logger.warning(f"Could not resolve entity: {system_url} ({public_id})")
                return None

        parser = etree.XMLParser(
            dtd_validation=True,
            load_dtd=True,
            resolve_entities=True,
            remove_blank_text=True,
            attribute_defaults=True,
            no_network=False  # Allow network access for DTD loading
        )
        
        resolver = DTDResolver(self.dtd_path)
        parser.resolvers.add(resolver)
        
        return parser

    def _validate_against_dtd(self, root: etree.Element, errors: List[ValidationError]) -> None:
        """Validate XML against DTD."""
        if not os.path.exists(self.dtd_path):
            errors.append(
                ValidationError(
                    element="dtd",
                    message=f"DTD file not found: {self.dtd_path}",
                    severity="critical",
                    suggestion="Check DTD path configuration"
                )
            )
            return

        try:
            # Create a DTD object
            dtd = etree.DTD(open(self.dtd_path, 'rb'))
            
            # Validate against DTD
            is_valid = dtd.validate(root)
            
            if not is_valid:
                # Process each validation error
                for error in dtd.error_log:
                    # Extract more meaningful information
                    element_match = re.search(r'Element ([\w-]+)', error.message)
                    element = element_match.group(1) if element_match else "unknown"
                    
                    # Try to provide helpful suggestions
                    suggestion = self._get_suggestion_for_dtd_error(error.message)
                    
                    errors.append(
                        ValidationError(
                            element=element,
                            message=error.message,
                            severity="error",
                            line_number=error.line,
                            suggestion=suggestion
                        )
                    )
        
        except Exception as e:
            errors.append(
                ValidationError(
                    element="dtd",
                    message=f"DTD validation error: {str(e)}",
                    severity="critical",
                    suggestion="Check DTD compatibility and XML structure"
                )
            )

    def _get_suggestion_for_dtd_error(self, error_msg: str) -> str:
        """Provide helpful suggestions for common DTD validation errors."""
        if "Element x not allowed" in error_msg:
            return "Remove this element or replace with an allowed element"
        
        if "Element x content does not follow" in error_msg:
            return "Check element order and required child elements"
        
        if "no declaration for" in error_msg:
            return "This element is not defined in the DTD. Check spelling or use a different element."
        
        if "required but not found" in error_msg:
            return "Add the required element"
        
        if "attribute x not allowed" in error_msg:
            return "Remove this attribute or check attribute name spelling"
        
        return "Check XML structure against PubMed DTD requirements"

    def generate_report(self, result: ValidationResult) -> str:
        """Generate a human-readable validation report."""
        lines = [
            "PubMed XML Validation Report",
            "===========================",
            f"Timestamp: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Valid: {'Yes' if result.is_valid else 'No'}",
            f"Errors: {len(result.errors)}",
            f"Warnings: {len(result.warnings)}",
            ""
        ]
        
        if result.errors:
            lines.append("Errors:")
            lines.append("-------")
            for i, error in enumerate(result.errors, 1):
                lines.append(f"{i}. {error.element}: {error.message}")
                if error.line_number:
                    lines.append(f"   Line: {error.line_number}")
                if error.suggestion:
                    lines.append(f"   Suggestion: {error.suggestion}")
                lines.append("")
        
        if result.warnings:
            lines.append("Warnings:")
            lines.append("---------")
            for i, warning in enumerate(result.warnings, 1):
                lines.append(f"{i}. {warning.element}: {warning.message}")
                if warning.suggestion:
                    lines.append(f"   Suggestion: {warning.suggestion}")
                lines.append("")
        
        if not result.errors and not result.warnings:
            lines.append("Congratulations! The XML is valid and has no warnings.")
        
        return "\n".join(lines)