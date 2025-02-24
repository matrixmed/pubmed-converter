import logging
from pathlib import Path
import argparse
import sys
from typing import Optional

from app.core import (
    PDFExtractor,
    MetadataExtractor,
    TextProcessor,
    XMLGenerator,
    XMLValidator
)

def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('conversion.log')
        ]
    )

def convert_pdf_to_xml(pdf_path: str, output_path: Optional[str] = None) -> bool:
    """
    Convert PDF to PubMed-compliant XML.
    
    Args:
        pdf_path: Path to input PDF file
        output_path: Optional path for output XML file
        
    Returns:
        bool: True if conversion successful, False otherwise
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Starting conversion of {pdf_path}")

    try:
        # Initialize components
        pdf_extractor = PDFExtractor()
        metadata_extractor = MetadataExtractor()
        text_processor = TextProcessor()
        xml_generator = XMLGenerator()
        xml_validator = XMLValidator()

        # Extract content from PDF
        extracted_content = pdf_extractor.extract(pdf_path)
        logger.info("PDF content extracted successfully")

        # Extract metadata
        journal_meta, article_meta = metadata_extractor.extract_metadata(extracted_content)
        logger.info("Metadata extracted successfully")

        # Process text content
        processed_content = text_processor.process(
            extracted_content=extracted_content,
            article_title=article_meta.title,
            abstract=article_meta.abstract
        )
        logger.info("Content processed successfully")

        # Generate XML
        xml_content = xml_generator.generate(
            journal_meta,
            article_meta,
            processed_content
        )
        logger.info("XML generated successfully")

        # Validate XML
        validation_result = xml_validator.validate(xml_content)
        is_valid = validation_result.is_valid
        validation_errors = validation_result.errors
        if not is_valid:
            logger.error("XML validation failed:")
            for error in validation_errors:
                logger.error(f"- {error.message}")
            return False

        # Write output
        output_file = output_path or pdf_path.replace('.pdf', '.xml')
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(xml_content)

        logger.info(f"XML saved to {output_file}")
        return True

    except Exception as e:
        logger.error(f"Conversion failed: {str(e)}", exc_info=True)
        return False

def main():
    """Main entry point for the converter."""
    parser = argparse.ArgumentParser(
        description="Convert PDF articles to PubMed-compliant XML"
    )
    parser.add_argument(
        "pdf_path",
        help="Path to the PDF file to convert"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output path for the XML file"
    )

    args = parser.parse_args()
    setup_logging()

    success = convert_pdf_to_xml(args.pdf_path, args.output)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()