import React, { useState } from "react";
import DropZone from "./DropZone";
import { FileDown } from "lucide-react";
import JSZip from "jszip";

const ConversionSpinner = () => (
  <div className="flex flex-col items-center justify-center p-10">
    <div className="relative">
      <div className="w-20 h-20 border-4 border-blue-200 rounded-full"></div>
      <div className="w-20 h-20 border-4 border-blue-600 rounded-full animate-spin absolute top-0 left-0 border-t-transparent"></div>
    </div>
    <p className="mt-4 text-blue-600 font-medium">Converting your document...</p>
  </div>
);

const SuccessDownload = ({ filename, onDownload }) => (
  <div className="flex flex-col items-center justify-center p-6 bg-green-50 rounded-lg">
    <div className="mb-4">
      <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
        <FileDown className="w-8 h-8 text-green-600" />
      </div>
    </div>
    <h3 className="text-lg font-medium text-green-900 mb-2">Conversion Complete!</h3>
    <p className="text-sm text-green-600 mb-4">{filename}</p>
    <button
      onClick={onDownload}
      className="flex items-center space-x-2 bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 transition-colors"
    >
      <FileDown className="w-4 h-4" />
      <span>Download ZIP</span>
    </button>
  </div>
);

const PDFtoXMLConverter = () => {
  const [articleType, setArticleType] = useState("abstract");
  const [pdfFile, setPdfFile] = useState(null);
  const [figures, setFigures] = useState([]);
  const [conversionState, setConversionState] = useState("idle"); // idle, converting, completed
  const [downloadUrl, setDownloadUrl] = useState(null);

  // NEW: State to store validation errors from validation_report.json
  const [validationErrors, setValidationErrors] = useState([]);

  const handlePDFUpload = (file) => {
    // Your existing logic
    if (file && (file.type === "application/pdf" || file[0]?.type === "application/pdf")) {
      const actualFile = file.type ? file : file[0];
      setPdfFile(actualFile);
      setConversionState("idle");
      setDownloadUrl(null);
      setValidationErrors([]); // reset errors if any
    } else {
      alert("Please upload a PDF file");
    }
  };

  const handleFigureUpload = (files) => {
    const imageFiles = Array.isArray(files) ? files : [files];
    setFigures((prev) => [...prev, ...imageFiles]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!pdfFile) {
      alert("Please select a PDF file first");
      return;
    }

    // Prepare formData
    const formData = new FormData();
    formData.append("pdf", pdfFile);
    formData.append("articleType", articleType);
    figures.forEach((fig) => formData.append("figures", fig));

    try {
      setConversionState("converting");

      // POST to your backend
      const response = await fetch("http://localhost:5000/convert", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        // If server returns a JSON error, parse it
        let data;
        try {
          data = await response.json();
        } catch {
          throw new Error("Conversion failed");
        }
        throw new Error(data.error || "Conversion failed");
      }

      // We get a ZIP file
      const zipBlob = await response.blob();

      // === NEW LOGIC: Parse the ZIP in memory with JSZip ===
      const arrayBuffer = await zipBlob.arrayBuffer();
      const zip = await JSZip.loadAsync(arrayBuffer);

      // 1) Extract validation_report.json if it exists
      const validationFile = zip.file("validation_report.json");
      if (validationFile) {
        const validationContent = await validationFile.async("string");
        const validationJson = JSON.parse(validationContent);
        if (validationJson.errors) {
          setValidationErrors(validationJson.errors);
        }
      }

      // 2) Create a blob URL for the entire ZIP so user can download it
      const zipUrl = window.URL.createObjectURL(zipBlob);
      setDownloadUrl(zipUrl);

      // 3) Transition to "completed" state
      setConversionState("completed");
    } catch (error) {
      console.error("Conversion error:", error);
      alert("Error: " + error.message);
      setConversionState("idle");
    }
  };

  const handleDownload = () => {
    if (downloadUrl) {
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = pdfFile.name.replace(".pdf", "") + ".zip";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      // Optionally reset states
      setConversionState("idle");
      setPdfFile(null);
      setFigures([]);
      setDownloadUrl(null);
      setValidationErrors([]);
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">PubMed XML Converter</h1>

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="space-y-2">
          <label className="block font-medium">Article Type</label>
          <select
            value={articleType}
            onChange={(e) => setArticleType(e.target.value)}
            className="w-full px-4 py-2 border rounded-lg"
          >
            <option value="abstract">Abstract</option>
            <option value="full">Full Research Article</option>
          </select>
        </div>

        <div className="space-y-2">
          <label className="block font-medium">Upload PDF</label>
          <DropZone
            onFileUpload={handlePDFUpload}
            accept=".pdf"
            multiple={false}
            label="pdf"
          />
        </div>

        <div className="space-y-2">
          <label className="block font-medium">Upload Figures (Optional)</label>
          <DropZone
            onFileUpload={handleFigureUpload}
            accept="image/*"
            multiple={true}
            label="figures"
          />
          {figures.length > 0 && (
            <div className="mt-2">
              <p className="text-sm text-gray-600">Uploaded Figures:</p>
              <ul className="list-disc pl-5 text-sm text-gray-600">
                {figures.map((fig, index) => (
                  <li key={index}>{fig.name}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* If we're converting, show spinner */}
        {conversionState === "converting" && <ConversionSpinner />}

        {/* If completed and we have a downloadUrl, show success */}
        {conversionState === "completed" && downloadUrl && (
          <SuccessDownload
            filename={pdfFile.name.replace(".pdf", "") + ".zip"}
            onDownload={handleDownload}
          />
        )}

        {/* Button to start conversion */}
        <button
          type="submit"
          className="w-full bg-blue-600 text-white py-2 px-4 rounded-lg hover:bg-blue-700 disabled:bg-gray-400"
          disabled={!pdfFile || conversionState === "converting"}
        >
          {conversionState === "converting" ? "Converting..." : "Convert to XML"}
        </button>
      </form>

      {/* Display Validation Errors from validation_report.json */}
      {validationErrors.length > 0 && (
        <div className="mt-6 p-4 bg-yellow-50 border border-yellow-300 rounded">
          <h2 className="text-lg font-semibold text-yellow-700 mb-2">
            Validation Errors/Warnings
          </h2>
          <ul className="list-disc list-inside">
            {validationErrors.map((err, idx) => (
              <li key={idx} className="text-yellow-800">
                <strong>{err.element}:</strong> {err.message}
                {err.suggestion && (
                  <em className="ml-2">
                    (Suggestion: {err.suggestion})
                  </em>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default PDFtoXMLConverter;
