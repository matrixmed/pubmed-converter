import React, { useState, useCallback } from 'react';
import { Upload } from 'lucide-react';

const DropZone = ({ onFileUpload, accept, multiple, label }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState([]);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setIsDragging(true);
    } else if (e.type === 'dragleave' || e.type === 'drop') {
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const droppedFiles = Array.from(e.dataTransfer.files);
    setFiles(prev => multiple ? [...prev, ...droppedFiles] : [droppedFiles[0]]);
    onFileUpload(multiple ? droppedFiles : droppedFiles[0]);
  }, [multiple, onFileUpload]);

  const handleChange = (e) => {
    const selectedFiles = Array.from(e.target.files);
    setFiles(prev => multiple ? [...prev, ...selectedFiles] : [selectedFiles[0]]);
    onFileUpload(multiple ? selectedFiles : selectedFiles[0]);
  };

  return (
    <div
      className={`relative border-2 border-dashed rounded-lg p-6 transition-all duration-300 ease-in-out
        ${isDragging 
          ? 'border-blue-500 bg-blue-50' 
          : 'border-gray-300 hover:border-gray-400'}`}
      onDragEnter={handleDrag}
      onDragOver={handleDrag}
      onDragLeave={handleDrag}
      onDrop={handleDrop}
    >
      <input
        type="file"
        onChange={handleChange}
        accept={accept}
        multiple={multiple}
        className="hidden"
        id={`fileInput-${label}`}
      />
      <label 
        htmlFor={`fileInput-${label}`} 
        className="flex flex-col items-center cursor-pointer"
      >
        <Upload 
          className={`w-12 h-12 mb-2 transition-colors duration-300
            ${isDragging ? 'text-blue-500' : 'text-gray-400'}`}
        />
        <span className={`text-sm transition-colors duration-300
          ${isDragging ? 'text-blue-600' : 'text-gray-600'}`}>
          {files.length > 0 
            ? `${files.length} file${files.length === 1 ? '' : 's'} selected`
            : `Click or drag ${multiple ? 'files' : 'a file'} to upload`}
        </span>
        {files.length > 0 && (
          <div className="mt-2 text-xs text-gray-500">
            {files.map((file, index) => (
              <div key={index} className="flex items-center space-x-2">
                <span>{file.name}</span>
              </div>
            ))}
          </div>
        )}
      </label>
      {isDragging && (
        <div className="absolute inset-0 bg-blue-50 bg-opacity-50 pointer-events-none 
          flex items-center justify-center rounded-lg">
          <span className="text-blue-600 font-medium">Drop files here</span>
        </div>
      )}
    </div>
  );
};

export default DropZone;