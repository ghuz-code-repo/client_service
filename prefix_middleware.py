class PrefixMiddleware:
    """
    Middleware for handling URL prefixes when an app is behind a reverse proxy.
    """
    def __init__(self, wsgi_app, app=None, prefix='/discount-system'):
        self.wsgi_app = wsgi_app
        self.app = app
        self.prefix = prefix.rstrip('/')
        
        print(f"PrefixMiddleware initialized with prefix: '{self.prefix}'")
        
        if app is not None:
            # Configure Flask app correctly
            app.config['APPLICATION_ROOT'] = self.prefix
            # Update static URL path
            app.static_url_path = self.prefix + '/static'
            print(f"Updated static_url_path to: {app.static_url_path}")
    
    def __call__(self, environ, start_response):
        script_name = environ.get('SCRIPT_NAME', '')
        path_info = environ.get('PATH_INFO', '')
        
        # Check for X-Forwarded-Prefix header (set by nginx)
        forwarded_prefix = environ.get('HTTP_X_FORWARDED_PREFIX', '').rstrip('/')
        
        # Debug: print all HTTP headers
        http_headers = {k: v for k, v in environ.items() if k.startswith('HTTP_')}
        print(f"Request before middleware: SCRIPT_NAME='{script_name}', PATH_INFO='{path_info}', X-Forwarded-Prefix='{forwarded_prefix}'")
        print(f"All HTTP headers: {http_headers}")
        
        # Special handling for static file requests (nginx sends /static/ without prefix)
        if path_info.startswith('/static'):
            # Static file request from nginx - no adjustments needed
            # Flask will handle it with its static file handler
            print(f"Static file request: PATH_INFO='{path_info}' - no prefix adjustment")
            return self.wsgi_app(environ, start_response)
        
        # If we have a forwarded prefix from nginx, always use it
        if forwarded_prefix:
            environ['SCRIPT_NAME'] = script_name + forwarded_prefix
            # PATH_INFO stays as is (already stripped by nginx rewrite)
            print(f"Using forwarded prefix: SCRIPT_NAME='{environ['SCRIPT_NAME']}', PATH_INFO='{environ['PATH_INFO']}'")
        # Fallback: If path starts with prefix, adjust PATH_INFO and SCRIPT_NAME
        elif path_info.startswith(self.prefix):
            environ['SCRIPT_NAME'] = script_name + self.prefix
            environ['PATH_INFO'] = path_info[len(self.prefix):] or '/'
            print(f"Path adjusted: SCRIPT_NAME='{environ['SCRIPT_NAME']}', PATH_INFO='{environ['PATH_INFO']}'")
        
        return self.wsgi_app(environ, start_response)
