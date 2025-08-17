<?php
/**
 * Configuration and utility functions for Dimension Index API
 */

// Error handling
error_reporting(E_ALL);
ini_set('display_errors', 0); // Don't display errors in production
ini_set('log_errors', 1);

// Set timezone
date_default_timezone_set('Europe/Bucharest');

// API Configuration
class Config {
    const DB_PATH = '../data/dimension_index.db';
    const MAX_RESULTS = 1000;
    const CACHE_TTL = 300; // 5 minutes
    const API_VERSION = '1.0.0';
    
    // Security settings
    const ALLOWED_ORIGINS = ['*']; // In production, specify exact origins
    const RATE_LIMIT_REQUESTS = 100;
    const RATE_LIMIT_WINDOW = 3600; // 1 hour
    
    // Database settings
    const DB_TIMEOUT = 10; // seconds
    const DB_CACHE_SIZE = 10000;
}

class ApiResponse {
    public static function success($data, $meta = []) {
        $response = [
            'success' => true,
            'data' => $data,
            'timestamp' => date('c'),
            'api_version' => Config::API_VERSION
        ];
        
        if (!empty($meta)) {
            $response['meta'] = $meta;
        }
        
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit;
    }
    
    public static function error($message, $code = 400, $details = []) {
        http_response_code($code);
        
        $response = [
            'success' => false,
            'error' => [
                'message' => $message,
                'code' => $code
            ],
            'timestamp' => date('c'),
            'api_version' => Config::API_VERSION
        ];
        
        if (!empty($details)) {
            $response['error']['details'] = $details;
        }
        
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit;
    }
}

class RateLimiter {
    private static $requests = [];
    
    public static function checkLimit($identifier = null) {
        if ($identifier === null) {
            $identifier = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
        }
        
        $now = time();
        $window_start = $now - Config::RATE_LIMIT_WINDOW;
        
        // Clean old entries
        if (isset(self::$requests[$identifier])) {
            self::$requests[$identifier] = array_filter(
                self::$requests[$identifier],
                function($timestamp) use ($window_start) {
                    return $timestamp > $window_start;
                }
            );
        } else {
            self::$requests[$identifier] = [];
        }
        
        // Check limit
        if (count(self::$requests[$identifier]) >= Config::RATE_LIMIT_REQUESTS) {
            ApiResponse::error('Rate limit exceeded', 429, [
                'limit' => Config::RATE_LIMIT_REQUESTS,
                'window' => Config::RATE_LIMIT_WINDOW,
                'reset_time' => date('c', $now + Config::RATE_LIMIT_WINDOW)
            ]);
        }
        
        // Record this request
        self::$requests[$identifier][] = $now;
    }
}

class DatabaseConnection {
    private static $instance = null;
    private $db;
    
    private function __construct() {
        if (!file_exists(Config::DB_PATH)) {
            throw new Exception("Database file not found: " . Config::DB_PATH);
        }
        
        try {
            $this->db = new SQLite3(Config::DB_PATH, SQLITE3_OPEN_READONLY);
            $this->db->enableExceptions(true);
            $this->db->busyTimeout(Config::DB_TIMEOUT * 1000);
            
            // Note: Skip PRAGMA commands that modify the database when opened read-only
            
        } catch (Exception $e) {
            throw new Exception("Database connection failed: " . $e->getMessage());
        }
    }
    
    public static function getInstance() {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance->db;
    }
    
    public function __destruct() {
        if ($this->db) {
            $this->db->close();
        }
    }
}

// Set CORS headers
function setCorsHeaders() {
    $origin = $_SERVER['HTTP_ORIGIN'] ?? '*';
    
    // In production, check against allowed origins
    if (Config::ALLOWED_ORIGINS[0] === '*' || in_array($origin, Config::ALLOWED_ORIGINS)) {
        header("Access-Control-Allow-Origin: {$origin}");
    }
    
    header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type, Authorization');
    header('Access-Control-Max-Age: 86400');
}

// Handle preflight requests
function handlePreflight() {
    if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
        setCorsHeaders();
        http_response_code(200);
        exit;
    }
}

// Validate and sanitize input
function validateInput($input, $type = 'string', $maxLength = 255) {
    if ($input === null || $input === '') {
        return null;
    }
    
    switch ($type) {
        case 'string':
            $input = trim($input);
            if (strlen($input) > $maxLength) {
                throw new InvalidArgumentException("Input too long (max {$maxLength} characters)");
            }
            return filter_var($input, FILTER_SANITIZE_STRING);
            
        case 'int':
            if (!is_numeric($input)) {
                throw new InvalidArgumentException("Invalid integer value");
            }
            return (int)$input;
            
        case 'filename':
            $input = trim($input);
            if (!preg_match('/^[a-zA-Z0-9_-]+$/', $input)) {
                throw new InvalidArgumentException("Invalid filename format");
            }
            return $input;
            
        default:
            return $input;
    }
}

// Log API usage (for monitoring)
function logApiUsage($action, $params = [], $responseTime = 0) {
    $logEntry = [
        'timestamp' => date('c'),
        'ip' => $_SERVER['REMOTE_ADDR'] ?? 'unknown',
        'user_agent' => $_SERVER['HTTP_USER_AGENT'] ?? 'unknown',
        'action' => $action,
        'params' => $params,
        'response_time_ms' => round($responseTime * 1000, 2)
    ];
    
    // In production, write to a log file or database
    // error_log(json_encode($logEntry), 3, 'api_usage.log');
}
?>
