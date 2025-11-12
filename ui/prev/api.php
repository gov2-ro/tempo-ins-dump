<?php
/**
 * Dimension Index API
 * PHP API for querying the SQLite dimension index database
 * 
 * Endpoints:
 * - GET /api.php?action=stats
 * - GET /api.php?action=search&query=term&type=all&file= (searches dimension labels, option labels, and matrix titles)
 * - GET /api.php?action=summary
 * - GET /api.php?action=usage
 * - GET /api.php?action=files
 * - GET /api.php?action=file_details&file_id=XXX
 */

require_once 'config.php';

// Handle CORS and preflight
setCorsHeaders();
handlePreflight();

class DimensionAPI {
    private $db;
    private $cache = [];
    private $startTime;
    
    public function __construct() {
        $this->startTime = microtime(true);
        
        try {
            // Check rate limit
            RateLimiter::checkLimit();
            
            // Get database connection
            $this->db = DatabaseConnection::getInstance();
            
        } catch (Exception $e) {
            ApiResponse::error("API initialization failed: " . $e->getMessage(), 500);
        }
    }
    
    public function handleRequest() {
        $action = validateInput($_GET['action'] ?? '', 'string', 50);
        
        if (empty($action)) {
            // Log the failed request with 'unknown' action
            $responseTime = microtime(true) - $this->startTime;
            logApiUsage('unknown', $_GET, $responseTime);
            
            ApiResponse::error("Missing 'action' parameter", 400, [
                'available_actions' => ['stats', 'search', 'summary', 'usage', 'files', 'file_details']
            ]);
            return;
        }
        
        try {
            switch ($action) {
                case 'stats':
                    $this->getStats();
                    break;
                    
                case 'search':
                    $query = validateInput($_GET['query'] ?? '', 'string', 100);
                    $type = validateInput($_GET['type'] ?? 'all', 'string', 20);
                    $file = validateInput($_GET['file'] ?? '', 'filename', 50);
                    $this->search($query, $type, $file);
                    break;
                    
                case 'summary':
                    $this->getSummary();
                    break;
                    
                case 'usage':
                    $this->getDimensionUsage();
                    break;
                    
                case 'files':
                    $this->getFiles();
                    break;
                    
                case 'file_details':
                    $fileId = validateInput($_GET['file_id'] ?? '', 'filename', 50);
                    $this->getFileDetails($fileId);
                    break;
                    
                default:
                    ApiResponse::error("Invalid action: {$action}", 400, [
                        'available_actions' => ['stats', 'search', 'summary', 'usage', 'files', 'file_details']
                    ]);
            }
        } catch (Exception $e) {
            ApiResponse::error("Request failed: " . $e->getMessage(), 500);
        }
        
        // Log usage
        $responseTime = microtime(true) - $this->startTime;
        logApiUsage($action, $_GET, $responseTime);
    }
    
    private function getStats() {
        $cacheKey = 'stats';
        if ($cached = $this->getCache($cacheKey)) {
            ApiResponse::success($cached);
            return;
        }
        
        $stats = [
            'total_files' => 0,
            'total_dimensions' => 0,
            'total_options' => 0,
            'last_updated' => null
        ];
        
        // Get file count
        $stmt = $this->db->prepare('SELECT COUNT(DISTINCT file_id) as count FROM dimensions');
        $result = $stmt->execute();
        $row = $result->fetchArray(SQLITE3_ASSOC);
        $stats['total_files'] = (int)$row['count'];
        
        // Get dimension count
        $stmt = $this->db->prepare('SELECT COUNT(*) as count FROM dimensions');
        $result = $stmt->execute();
        $row = $result->fetchArray(SQLITE3_ASSOC);
        $stats['total_dimensions'] = (int)$row['count'];
        
        // Get option count
        $stmt = $this->db->prepare('SELECT COUNT(*) as count FROM options');
        $result = $stmt->execute();
        $row = $result->fetchArray(SQLITE3_ASSOC);
        $stats['total_options'] = (int)$row['count'];
        
        // Get database file modification time
        if (file_exists(Config::DB_PATH)) {
            $stats['last_updated'] = date('c', filemtime(Config::DB_PATH));
        }
        
        $this->setCache($cacheKey, $stats);
        ApiResponse::success($stats);
    }
    
    private function search($query, $type, $file) {
        if (empty($query)) {
            ApiResponse::error("Query parameter is required", 400);
            return;
        }
        
        if (strlen($query) < 2) {
            ApiResponse::error("Query must be at least 2 characters long", 400);
            return;
        }
        
        $results = [
            'query' => $query,
            'type' => $type,
            'file_filter' => $file,
            'dimensions' => [],
            'options' => [],
            'total_count' => 0
        ];
        
        // Search dimensions (including matrix names)
        if ($type === 'all' || $type === 'dimensions') {
            $sql = "SELECT id, label, dim_code, file_id, matrix_name FROM dimensions WHERE (label LIKE :query OR matrix_name LIKE :query)";
            $params = [':query' => "%{$query}%"];
            
            if (!empty($file)) {
                $sql .= " AND file_id = :file";
                $params[':file'] = $file;
            }
            
            $sql .= " ORDER BY label, file_id LIMIT " . Config::MAX_RESULTS;
            
            $stmt = $this->db->prepare($sql);
            foreach ($params as $key => $value) {
                $stmt->bindValue($key, $value, SQLITE3_TEXT);
            }
            
            $result = $stmt->execute();
            while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
                $results['dimensions'][] = [
                    'id' => (int)$row['id'],
                    'label' => $row['label'],
                    'dim_code' => (int)$row['dim_code'],
                    'file_id' => $row['file_id'],
                    'matrix_name' => $row['matrix_name']
                ];
            }
        }
        
        // Search options (including matrix names)
        if ($type === 'all' || $type === 'options') {
            $sql = "SELECT o.id, o.label, o.nom_item_id, o.offset_value, o.file_id, 
                           d.label as dimension_label, d.matrix_name 
                    FROM options o 
                    JOIN dimensions d ON o.dimension_id = d.id 
                    WHERE (o.label LIKE :query OR d.matrix_name LIKE :query)";
            $params = [':query' => "%{$query}%"];
            
            if (!empty($file)) {
                $sql .= " AND o.file_id = :file";
                $params[':file'] = $file;
            }
            
            $sql .= " ORDER BY o.label, o.file_id LIMIT " . Config::MAX_RESULTS;
            
            $stmt = $this->db->prepare($sql);
            foreach ($params as $key => $value) {
                $stmt->bindValue($key, $value, SQLITE3_TEXT);
            }
            
            $result = $stmt->execute();
            while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
                $results['options'][] = [
                    'id' => (int)$row['id'],
                    'label' => $row['label'],
                    'nom_item_id' => $row['nom_item_id'] ? (int)$row['nom_item_id'] : null,
                    'offset_value' => $row['offset_value'] ? (int)$row['offset_value'] : null,
                    'file_id' => $row['file_id'],
                    'dimension_label' => $row['dimension_label'],
                    'matrix_name' => $row['matrix_name']
                ];
            }
        }
        
        $results['total_count'] = count($results['dimensions']) + count($results['options']);
        
        $meta = [
            'search_time_ms' => round((microtime(true) - $this->startTime) * 1000, 2),
            'max_results' => Config::MAX_RESULTS
        ];
        
        ApiResponse::success($results, $meta);
    }
    
    private function getSummary() {
        $cacheKey = 'summary';
        if ($cached = $this->getCache($cacheKey)) {
            ApiResponse::success($cached);
            return;
        }
        
        $sql = "SELECT 
                    d.file_id,
                    d.matrix_name,
                    COUNT(DISTINCT d.id) as dimension_count,
                    COUNT(o.id) as option_count
                FROM dimensions d
                LEFT JOIN options o ON d.id = o.dimension_id
                GROUP BY d.file_id, d.matrix_name
                ORDER BY d.file_id";
        
        $stmt = $this->db->prepare($sql);
        $result = $stmt->execute();
        
        $summary = [];
        while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
            $summary[] = [
                'file_id' => $row['file_id'],
                'matrix_name' => $row['matrix_name'],
                'dimension_count' => (int)$row['dimension_count'],
                'option_count' => (int)$row['option_count']
            ];
        }
        
        $this->setCache($cacheKey, $summary);
        
        $meta = [
            'search_time_ms' => round((microtime(true) - $this->startTime) * 1000, 2),
            'total_files' => count($summary)
        ];
        
        ApiResponse::success($summary, $meta);
    }
    
    private function getDimensionUsage() {
        $cacheKey = 'usage';
        if ($cached = $this->getCache($cacheKey)) {
            ApiResponse::success($cached);
            return;
        }
        
        $sql = "SELECT 
                    label,
                    COUNT(*) as file_count,
                    GROUP_CONCAT(file_id, ', ') as files
                FROM dimensions
                GROUP BY label
                ORDER BY file_count DESC, label";
        
        $stmt = $this->db->prepare($sql);
        $result = $stmt->execute();
        
        $usage = [];
        while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
            $usage[] = [
                'label' => $row['label'],
                'file_count' => (int)$row['file_count'],
                'files' => explode(', ', $row['files'])
            ];
        }
        
        $this->setCache($cacheKey, $usage);
        
        $meta = [
            'search_time_ms' => round((microtime(true) - $this->startTime) * 1000, 2),
            'total_dimensions' => count($usage)
        ];
        
        ApiResponse::success($usage, $meta);
    }
    
    private function getFiles() {
        $cacheKey = 'files';
        if ($cached = $this->getCache($cacheKey)) {
            ApiResponse::success($cached);
            return;
        }
        
        $sql = "SELECT DISTINCT file_id FROM dimensions ORDER BY file_id";
        $stmt = $this->db->prepare($sql);
        $result = $stmt->execute();
        
        $files = [];
        while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
            $files[] = $row['file_id'];
        }
        
        $this->setCache($cacheKey, $files);
        
        $meta = [
            'search_time_ms' => round((microtime(true) - $this->startTime) * 1000, 2),
            'count' => count($files)
        ];
        
        ApiResponse::success($files, $meta);
    }
    
    private function getFileDetails($fileId) {
        if (empty($fileId)) {
            ApiResponse::error("file_id parameter is required", 400);
            return;
        }
        
        $cacheKey = "file_details_{$fileId}";
        if ($cached = $this->getCache($cacheKey)) {
            ApiResponse::success($cached);
            return;
        }
        
        // Get file info
        $sql = "SELECT DISTINCT file_id, matrix_name FROM dimensions WHERE file_id = :file_id";
        $stmt = $this->db->prepare($sql);
        $stmt->bindValue(':file_id', $fileId, SQLITE3_TEXT);
        $result = $stmt->execute();
        $fileInfo = $result->fetchArray(SQLITE3_ASSOC);
        
        if (!$fileInfo) {
            ApiResponse::error("File not found: {$fileId}", 404);
            return;
        }
        
        // Get dimensions and their options
        $sql = "SELECT 
                    d.id, d.label, d.dim_code,
                    o.label as option_label, o.nom_item_id, o.offset_value
                FROM dimensions d
                LEFT JOIN options o ON d.id = o.dimension_id
                WHERE d.file_id = :file_id
                ORDER BY d.dim_code, o.offset_value";
        
        $stmt = $this->db->prepare($sql);
        $stmt->bindValue(':file_id', $fileId, SQLITE3_TEXT);
        $result = $stmt->execute();
        
        $dimensions = [];
        $currentDim = null;
        
        while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
            if ($currentDim === null || $currentDim['id'] !== (int)$row['id']) {
                if ($currentDim !== null) {
                    $dimensions[] = $currentDim;
                }
                $currentDim = [
                    'id' => (int)$row['id'],
                    'label' => $row['label'],
                    'dim_code' => (int)$row['dim_code'],
                    'options' => []
                ];
            }
            
            if ($row['option_label']) {
                $currentDim['options'][] = [
                    'label' => $row['option_label'],
                    'nom_item_id' => $row['nom_item_id'] ? (int)$row['nom_item_id'] : null,
                    'offset_value' => $row['offset_value'] ? (int)$row['offset_value'] : null
                ];
            }
        }
        
        if ($currentDim !== null) {
            $dimensions[] = $currentDim;
        }
        
        $fileDetails = [
            'file_id' => $fileInfo['file_id'],
            'matrix_name' => $fileInfo['matrix_name'],
            'dimensions' => $dimensions,
            'dimension_count' => count($dimensions),
            'total_options' => array_sum(array_map(function($d) { return count($d['options']); }, $dimensions))
        ];
        
        $this->setCache($cacheKey, $fileDetails);
        
        $meta = [
            'search_time_ms' => round((microtime(true) - $this->startTime) * 1000, 2)
        ];
        
        ApiResponse::success($fileDetails, $meta);
    }
    
    private function getCache($key) {
        $filePath = sys_get_temp_dir() . "/dimension_api_{$key}.cache";
        if (!file_exists($filePath)) {
            return null;
        }
        
        $data = file_get_contents($filePath);
        $item = json_decode($data, true);
        
        if (!$item || !isset($item['timestamp'], $item['data'])) {
            return null;
        }
        
        // Check if cache is expired
        if (time() - $item['timestamp'] > Config::CACHE_TTL) {
            unlink($filePath);
            return null;
        }
        
        return $item['data'];
    }
    
    private function setCache($key, $data) {
        $this->cache[$key] = [
            'data' => $data,
            'timestamp' => time()
        ];
    }
    
    private function sendResponse($data) {
        $response = [
            'success' => true,
            'data' => $data,
            'timestamp' => date('c')
        ];
        
        echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit();
    }
    
    private function sendError($message, $code = 400) {
        http_response_code($code);
        
        $response = [
            'success' => false,
            'error' => $message,
            'timestamp' => date('c')
        ];
        
        echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit();
    }
    
    public function __destruct() {
        if ($this->db) {
            $this->db->close();
        }
    }
}

// Initialize and handle request
try {
    $api = new DimensionAPI();
    $api->handleRequest();
} catch (Exception $e) {
    http_response_code(500);
    echo json_encode([
        'success' => false,
        'error' => 'Internal server error: ' . $e->getMessage(),
        'timestamp' => date('c')
    ], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
}
?>
