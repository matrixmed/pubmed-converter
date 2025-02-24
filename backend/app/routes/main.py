# app/routes/main.py

from flask import Blueprint, request, jsonify, send_file
from werkzeug.datastructures import FileStorage
from typing import List, Dict, Optional, Tuple
import logging
import os
import time
import hashlib
import json
import zipfile
import tempfile
from io import BytesIO
from dataclasses import asdict

from app.core.pdf_extractor import PDFExtractor
from app.core.metadata_extractor import MetadataExtractor
from app.core.text_processor import TextProcessor
from app.core.xml_generator import XMLGenerator
from app.core.xml_validator import XMLValidator

main = Blueprint('main', __name__)
logger = logging.getLogger(__name__)

def setup_logging():
    """Configure detailed logging for the routes"""
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

class ConversionManager:
    def __init__(self):
        self.pdf_extractor = PDFExtractor()
        self.metadata_extractor = MetadataExtractor()
        self.text_processor = TextProcessor()
        self.xml_generator = XMLGenerator()
        self.xml_validator = XMLValidator()
        
    def validate_file(self, file: FileStorage) -> Tuple[bool, Optional[str]]:
        """Validate uploaded file"""
        if not file or not file.filename:
            return False, "No file provided"
            
        if not file.filename.endswith('.pdf'):
            return False, "File must be a PDF"
            
        # Check file size (e.g., 50MB limit)
        if file.content_length and file.content_length > 50 * 1024 * 1024:
            return False, "File size exceeds 50MB limit"
            
        return True, None
        
    def process_figures(self, figures: List[FileStorage]) -> List[Dict]:
        """Process and validate figure files"""
        processed_figures = []
        allowed_extensions = {'.png', '.jpg', '.jpeg', '.tiff', '.gif'}
        
        for figure in figures:
            ext = os.path.splitext(figure.filename)[1].lower()
            if ext not in allowed_extensions:
                logger.warning(f"Skipping invalid figure file: {figure.filename}")
                continue
                
            processed_figures.append({
                'filename': figure.filename,
                'data': figure.read(),
                'mime_type': figure.content_type
            })
            figure.seek(0)  # Reset file pointer
            
        return processed_figures

    def create_zip_archive(self, pdf_file: FileStorage, xml_content: str, 
                            figures: List[Dict]) -> BytesIO:
        """Create ZIP archive with converted content"""
        memory_file = BytesIO()
        
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add PDF
            pdf_data = pdf_file.read()
            pdf_file.seek(0)
            zf.writestr(pdf_file.filename, pdf_data)
            
            # Add XML
            xml_filename = f"{os.path.splitext(pdf_file.filename)[0]}.xml"
            zf.writestr(xml_filename, xml_content)
            
            # Add figures
            if figures:
                for figure in figures:
                    zf.writestr(f"figures/{figure['filename']}", figure['data'])
            
            # Add validation report
            validation_result = self.xml_validator.validate(xml_content)
            validation_result_json = json.dumps(
                asdict(validation_result),
                indent=2,
                default=str  # This will convert datetime to string automatically
            )
            zf.writestr("validation_report.json", validation_result_json)
            
        memory_file.seek(0)
        return memory_file


    def convert_pdf(self, pdf_file: str, article_type: str, figures: List[Dict]) -> Tuple[str, List[str]]:
        """Convert PDF to XML using the full pipeline"""
        # Extract content from PDF
        extracted_content = self.pdf_extractor.extract(pdf_file)
        
        # Extract metadata
        journal_meta, article_meta = self.metadata_extractor.extract_metadata(
            extracted_content,
            user_article_type=article_type  # Pass the article_type here
        )
        
        # Process content - Now passing the required article_title!
        processed_content = self.text_processor.process(
            extracted_content=extracted_content,
            article_title=article_meta.title,  # Add this
            abstract=article_meta.abstract     # Optional but useful
        )
        
        # Generate XML
        xml_content = self.xml_generator.generate(
            journal_meta=journal_meta,
            article_meta=article_meta,
            processed_content=processed_content  # Pass the full processed_content object
        )
        
        # Validate XML
        validation_result = self.xml_validator.validate(xml_content)
        is_valid = validation_result.is_valid
        validation_errors = validation_result.errors
        
        return xml_content, validation_errors

@main.route('/convert', methods=['POST'])
def convert_pdf():
    """Convert PDF to XML with comprehensive error handling and validation"""
    setup_logging()
    conversion_manager = ConversionManager()
    start_time = time.time()
    request_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    
    logger.info(f"Starting conversion request {request_id}")
    
    try:
        # Validate request
        if 'pdf' not in request.files:
            logger.error(f"Request {request_id}: No PDF file in request")
            return jsonify({'error': 'No PDF file provided'}), 400
        
        pdf_file = request.files['pdf']
        is_valid, error_msg = conversion_manager.validate_file(pdf_file)
        if not is_valid:
            logger.error(f"Request {request_id}: {error_msg}")
            return jsonify({'error': error_msg}), 400
            
        # Process figures if present
        figures = conversion_manager.process_figures(request.files.getlist('figures'))
        
        # Save PDF temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            pdf_file.save(temp_pdf.name)
            temp_path = temp_pdf.name
        
        try:
            # Convert PDF to XML
            logger.info(f"Request {request_id}: Converting PDF")
            article_type = request.form.get('articleType', 'research-article')
            
            xml_content, validation_errors = conversion_manager.convert_pdf(
                pdf_file=temp_path,
                article_type=article_type,
                figures=figures
            )
            
            # Create ZIP archive
            logger.info(f"Request {request_id}: Creating ZIP archive")
            memory_file = conversion_manager.create_zip_archive(pdf_file, xml_content, figures)
            
            # Prepare response
            zip_filename = f"{os.path.splitext(pdf_file.filename)[0]}.zip"
            processing_time = time.time() - start_time
            
            logger.info(f"Request {request_id}: Conversion completed in {processing_time:.2f} seconds")
            
            return send_file(
                memory_file,
                mimetype='application/zip',
                as_attachment=True,
                download_name=zip_filename
            )
            
        finally:
            # Clean up temporary file
            os.unlink(temp_path)
            
    except Exception as e:
        logger.exception(f"Request {request_id}: Unexpected error")
        return jsonify({
            'error': str(e),
            'request_id': request_id,
            'processing_time': time.time() - start_time
        }), 500

@main.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time(),
        'components': {
            'pdf_extractor': 'ok',
            'metadata_extractor': 'ok',
            'text_processor': 'ok',
            'xml_generator': 'ok',
            'xml_validator': 'ok'
        }
    })