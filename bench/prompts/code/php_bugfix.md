Find and fix the bug in this PHP function.

```php
function public_url(string $base, string $path): string {
    if ($path[0] !== '/') {
        $path = '/' . $path;
    }
    return rtrim($base, '/') . $path;
}

echo public_url('https://example.com/app/', '');
```

Requirements:
- explain the bug briefly
- provide a corrected function
- include 4 small test cases
