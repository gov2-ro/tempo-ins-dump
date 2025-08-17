<?php
/**
 * PHP Test and API Info
 */

header('Content-Type: application/json; charset=utf-8');

$info = [
    'php_version' => phpversion(),
    'sqlite3_available' => extension_loaded('sqlite3'),
    'database_path' => '../data/dimension_index.db',
    'database_exists' => file_exists('../data/dimension_index.db'),
    'api_endpoints' => [
        'stats' => 'GET api.php?action=stats',
        'search' => 'GET api.php?action=search&query=term&type=all&file=',
        'summary' => 'GET api.php?action=summary',
        'usage' => 'GET api.php?action=usage',
        'files' => 'GET api.php?action=files',
        'file_details' => 'GET api.php?action=file_details&file_id=XXX'
    ],
    'timestamp' => date('c')
];

if (file_exists('../data/dimension_index.db')) {
    $info['database_size'] = filesize('../data/dimension_index.db');
    $info['database_modified'] = date('c', filemtime('../data/dimension_index.db'));
}

echo json_encode($info, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
?>
