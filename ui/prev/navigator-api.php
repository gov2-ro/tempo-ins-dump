<?php
/**
 * Enhanced Navigator API
 * Provides fast, filterable access to dataset metadata
 */

require_once 'config.php';

// Enhanced API Configuration
class NavigatorConfig extends Config {
    const ENHANCED_DB_PATH = './data/enhanced_navigator.db';
    const STATIC_INDEX_PATH = './data/navigation_index.json';
    const DEFAULT_PAGE_SIZE = 50;
    const MAX_PAGE_SIZE = 200;
}

class NavigatorAPI {
    private $db;
    private static $static_cache = null;
    
    public function __construct() {
        if (!file_exists(NavigatorConfig::ENHANCED_DB_PATH)) {
            throw new Exception("Enhanced navigator database not found. Please run build-enhanced-navigator-index.py");
        }
        
        try {
            $this->db = new SQLite3(NavigatorConfig::ENHANCED_DB_PATH, SQLITE3_OPEN_READONLY);
            $this->db->enableExceptions(true);
            $this->db->busyTimeout(NavigatorConfig::DB_TIMEOUT * 1000);
        } catch (Exception $e) {
            throw new Exception("Database connection failed: " . $e->getMessage());
        }
    }
    
    private function getStaticData() {
        if (self::$static_cache === null) {
            if (!file_exists(NavigatorConfig::STATIC_INDEX_PATH)) {
                throw new Exception("Static navigation index not found");
            }
            self::$static_cache = json_decode(file_get_contents(NavigatorConfig::STATIC_INDEX_PATH), true);
        }
        return self::$static_cache;
    }
    
    public function handleRequest() {
        handlePreflight();
        setCorsHeaders();
        RateLimiter::checkLimit();
        
        $action = validateInput($_GET['action'] ?? 'datasets', 'string', 50);
        
        $start_time = microtime(true);
        
        try {
            switch ($action) {
                case 'datasets':
                    $result = $this->getDatasets();
                    break;
                case 'navigation':
                    $result = $this->getNavigation();
                    break;
                case 'filters':
                    $result = $this->getFilters();
                    break;
                case 'stats':
                    $result = $this->getStats();
                    break;
                case 'suggestions':
                    $result = $this->getSearchSuggestions();
                    break;
                case 'dataset':
                    $result = $this->getDatasetDetail();
                    break;
                default:
                    throw new InvalidArgumentException("Unknown action: $action");
            }
            
            $response_time = microtime(true) - $start_time;
            logApiUsage($action, $_GET, $response_time);
            
            ApiResponse::success($result, [
                'search_time_ms' => round($response_time * 1000, 2),
                'action' => $action
            ]);
            
        } catch (Exception $e) {
            ApiResponse::error($e->getMessage(), 400);
        }
    }
    
    private function getDatasets() {
        // Parse and validate parameters
        $params = $this->parseDatasetFilters();
        
        // Build SQL query
        $sql = "SELECT * FROM datasets WHERE 1=1";
        $bind_params = [];
        $conditions = [];
        
        // Text search
        if ($params['search']) {
            $conditions[] = "search_text LIKE ?";
            $bind_params[] = '%' . $params['search'] . '%';
        }
        
        // Category/theme filters
        if ($params['theme_code']) {
            $conditions[] = "theme_code = ?";
            $bind_params[] = $params['theme_code'];
        }
        
        if ($params['context_code']) {
            $conditions[] = "context_code = ?";
            $bind_params[] = $params['context_code'];
        }
        
        // Metadata filters
        if ($params['periodicity']) {
            $conditions[] = "periodicity = ?";
            $bind_params[] = $params['periodicity'];
        }
        
        if ($params['geographic_level']) {
            $conditions[] = "geographic_level = ?";
            $bind_params[] = $params['geographic_level'];
        }
        
        if ($params['min_quality']) {
            $conditions[] = "quality_score >= ?";
            $bind_params[] = $params['min_quality'];
        }
        
        if ($params['has_recent_data'] !== null) {
            $conditions[] = "has_recent_data = ?";
            $bind_params[] = $params['has_recent_data'] ? 1 : 0;
        }
        
        if ($params['has_methodology'] !== null) {
            $conditions[] = "methodology_available = ?";
            $bind_params[] = $params['has_methodology'] ? 1 : 0;
        }
        
        // Time range filters
        if ($params['year_from']) {
            $conditions[] = "time_span_end >= ?";
            $bind_params[] = $params['year_from'];
        }
        
        if ($params['year_to']) {
            $conditions[] = "time_span_start <= ?";
            $bind_params[] = $params['year_to'];
        }
        
        // Add conditions to query
        if ($conditions) {
            $sql .= " AND " . implode(" AND ", $conditions);
        }
        
        // Get total count
        $count_sql = "SELECT COUNT(*) FROM datasets WHERE 1=1";
        if ($conditions) {
            $count_sql .= " AND " . implode(" AND ", $conditions);
        }
        
        $count_stmt = $this->db->prepare($count_sql);
        if ($bind_params) {
            foreach ($bind_params as $i => $param) {
                $count_stmt->bindValue($i + 1, $param);
            }
        }
        $total = $count_stmt->execute()->fetchArray()[0];
        
        // Add sorting
        $sort_field = $params['sort'] ?? 'title';
        $sort_order = $params['order'] ?? 'ASC';
        
        $valid_sorts = ['title', 'last_update', 'quality_score', 'dimensions_count', 'update_year'];
        if (!in_array($sort_field, $valid_sorts)) {
            $sort_field = 'title';
        }
        
        $sql .= " ORDER BY $sort_field $sort_order";
        
        // Add pagination
        $sql .= " LIMIT ? OFFSET ?";
        $bind_params[] = $params['limit'];
        $bind_params[] = $params['offset'];
        
        // Execute main query
        $stmt = $this->db->prepare($sql);
        foreach ($bind_params as $i => $param) {
            $stmt->bindValue($i + 1, $param);
        }
        
        $result = $stmt->execute();
        $datasets = [];
        
        while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
            $datasets[] = [
                'id' => $row['id'],
                'title' => $row['title'],
                'context_code' => $row['context_code'],
                'category_path' => $row['category_path'],
                'theme_code' => $row['theme_code'],
                'description' => substr($row['description'] ?? '', 0, 200) . '...',
                'periodicity' => $row['periodicity'],
                'last_update' => $row['last_update'],
                'dimensions_count' => (int)$row['dimensions_count'],
                'geographic_level' => $row['geographic_level'],
                'quality_score' => (float)$row['quality_score'],
                'has_recent_data' => (bool)$row['has_recent_data'],
                'um_label' => $row['um_label'],
                'keywords' => array_slice(explode(', ', $row['keywords'] ?? ''), 0, 5)
            ];
        }
        
        return [
            'datasets' => $datasets,
            'pagination' => [
                'total' => $total,
                'page' => intval($params['offset'] / $params['limit']) + 1,
                'limit' => $params['limit'],
                'total_pages' => ceil($total / $params['limit'])
            ],
            'filters_applied' => array_filter($params, function($v, $k) {
                return $v !== null && $v !== '' && !in_array($k, ['limit', 'offset', 'sort', 'order']);
            }, ARRAY_FILTER_USE_BOTH)
        ];
    }
    
    private function parseDatasetFilters() {
        return [
            'search' => validateInput($_GET['q'] ?? '', 'string', 255),
            'theme_code' => validateInput($_GET['theme'] ?? '', 'string', 50),
            'context_code' => validateInput($_GET['category'] ?? '', 'string', 50),
            'periodicity' => validateInput($_GET['periodicity'] ?? '', 'string', 50),
            'geographic_level' => validateInput($_GET['geo_level'] ?? '', 'string', 50),
            'min_quality' => $_GET['min_quality'] ? (float)$_GET['min_quality'] : null,
            'has_recent_data' => isset($_GET['recent']) ? filter_var($_GET['recent'], FILTER_VALIDATE_BOOLEAN) : null,
            'has_methodology' => isset($_GET['methodology']) ? filter_var($_GET['methodology'], FILTER_VALIDATE_BOOLEAN) : null,
            'year_from' => validateInput($_GET['year_from'] ?? '', 'int'),
            'year_to' => validateInput($_GET['year_to'] ?? '', 'int'),
            'limit' => min(validateInput($_GET['limit'] ?? NavigatorConfig::DEFAULT_PAGE_SIZE, 'int'), NavigatorConfig::MAX_PAGE_SIZE),
            'offset' => validateInput($_GET['offset'] ?? 0, 'int'),
            'sort' => validateInput($_GET['sort'] ?? 'title', 'string', 50),
            'order' => in_array(strtoupper($_GET['order'] ?? 'ASC'), ['ASC', 'DESC']) ? strtoupper($_GET['order']) : 'ASC'
        ];
    }
    
    private function getNavigation() {
        $static_data = $this->getStaticData();
        return $static_data['navigation_tree'];
    }
    
    private function getFilters() {
        $static_data = $this->getStaticData();
        return $static_data['filter_options'];
    }
    
    private function getStats() {
        $static_data = $this->getStaticData();
        
        // Add real-time stats
        $stmt = $this->db->query("SELECT 
            COUNT(*) as total_datasets,
            COUNT(CASE WHEN has_recent_data = 1 THEN 1 END) as recent_datasets,
            AVG(quality_score) as avg_quality,
            COUNT(DISTINCT theme_code) as total_themes
        FROM datasets");
        
        $real_time_stats = $stmt->fetchArray(SQLITE3_ASSOC);
        
        return array_merge($static_data['stats'], [
            'real_time' => $real_time_stats
        ]);
    }
    
    private function getSearchSuggestions() {
        $query = validateInput($_GET['q'] ?? '', 'string', 100);
        
        if (strlen($query) < 2) {
            $static_data = $this->getStaticData();
            return array_slice($static_data['search_suggestions'], 0, 10);
        }
        
        // Search in titles and keywords for autocomplete
        $stmt = $this->db->prepare("
            SELECT DISTINCT title FROM datasets 
            WHERE title LIKE ? 
            ORDER BY title 
            LIMIT 10
        ");
        $stmt->bindValue(1, '%' . $query . '%');
        $result = $stmt->execute();
        
        $suggestions = [];
        while ($row = $result->fetchArray()) {
            $suggestions[] = $row['title'];
        }
        
        return $suggestions;
    }
    
    private function getDatasetDetail() {
        $id = validateInput($_GET['id'] ?? '', 'string', 50);
        if (!$id) {
            throw new InvalidArgumentException("Dataset ID required");
        }
        
        $stmt = $this->db->prepare("SELECT * FROM datasets WHERE id = ?");
        $stmt->bindValue(1, $id);
        $result = $stmt->execute();
        
        $dataset = $result->fetchArray(SQLITE3_ASSOC);
        if (!$dataset) {
            throw new Exception("Dataset not found");
        }
        
        // Convert string fields back to arrays
        $dataset['keywords'] = array_filter(explode(', ', $dataset['keywords'] ?? ''));
        $dataset['dimensions_list'] = array_filter(explode(', ', $dataset['dimensions_list'] ?? ''));
        
        return $dataset;
    }
    
    public function __destruct() {
        if ($this->db) {
            $this->db->close();
        }
    }
}

// Handle the request
try {
    $api = new NavigatorAPI();
    $api->handleRequest();
} catch (Exception $e) {
    ApiResponse::error("API initialization failed: " . $e->getMessage(), 500);
}
?>