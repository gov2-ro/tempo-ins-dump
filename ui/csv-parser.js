/**
 * Lightweight CSV parser for client-side usage
 * Handles basic CSV parsing with configurable row limits
 */

class CSVParser {
  constructor() {
    this.maxFileSize = 4 * 1024 * 1024; // 4MB
    this.defaultMaxRows = 400;
  }

  /**
   * Parse CSV text into array of objects
   * @param {string} csvText - Raw CSV content
   * @param {number} maxRows - Maximum rows to parse (null = no limit)
   * @returns {Object} - {rows, columns, totalRows, isTruncated}
   */
  parse(csvText, maxRows = null) {
    const lines = csvText.split('\n').filter(line => line.trim());
    if (lines.length === 0) {
      return { rows: [], columns: [], totalRows: 0, isTruncated: false };
    }

    // Parse header
    const columns = this.parseCSVLine(lines[0]);
    
    // Determine if we should truncate
    const actualMaxRows = maxRows || (lines.length > this.defaultMaxRows ? this.defaultMaxRows : null);
    const dataLines = actualMaxRows ? lines.slice(1, actualMaxRows + 1) : lines.slice(1);
    const isTruncated = actualMaxRows && lines.length > actualMaxRows + 1;

    // Parse data rows
    const rows = dataLines.map(line => {
      const values = this.parseCSVLine(line);
      const row = {};
      columns.forEach((col, index) => {
        row[col] = values[index] || null;
      });
      return row;
    });

    return {
      rows,
      columns,
      totalRows: rows.length,
      actualTotalRows: lines.length - 1, // Total rows in file (excluding header)
      isTruncated
    };
  }

  /**
   * Parse a single CSV line handling quotes and commas
   * @param {string} line - CSV line
   * @returns {Array} - Array of values
   */
  parseCSVLine(line) {
    const result = [];
    let current = '';
    let inQuotes = false;
    let i = 0;

    while (i < line.length) {
      const char = line[i];
      const nextChar = line[i + 1];

      if (char === '"') {
        if (inQuotes && nextChar === '"') {
          // Escaped quote
          current += '"';
          i += 2;
        } else {
          // Toggle quote state
          inQuotes = !inQuotes;
          i++;
        }
      } else if (char === ',' && !inQuotes) {
        // Field separator
        result.push(this.cleanValue(current));
        current = '';
        i++;
      } else {
        current += char;
        i++;
      }
    }

    // Add the last field
    result.push(this.cleanValue(current));
    return result;
  }

  /**
   * Clean and normalize CSV value
   * @param {string} value - Raw value
   * @returns {string|null} - Cleaned value
   */
  cleanValue(value) {
    value = value.trim();
    if (value === '' || value.toLowerCase() === 'null') {
      return null;
    }
    return value;
  }

  /**
   * Check if file should be truncated based on size
   * @param {number} fileSize - File size in bytes
   * @returns {boolean} - Should truncate
   */
  shouldTruncate(fileSize) {
    return fileSize > this.maxFileSize;
  }

  /**
   * Get file size in MB
   * @param {number} fileSize - File size in bytes
   * @returns {number} - Size in MB
   */
  getFileSizeMB(fileSize) {
    return Math.round((fileSize / (1024 * 1024)) * 100) / 100;
  }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = CSVParser;
} else {
  window.CSVParser = CSVParser;
}
