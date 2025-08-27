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
        
        # Debug log every request
        print(f"Request before middleware: SCRIPT_NAME='{script_name}', PATH_INFO='{path_info}'")
        
        # If path starts with prefix, adjust PATH_INFO and SCRIPT_NAME
        if path_info.startswith(self.prefix):
            environ['SCRIPT_NAME'] = script_name + self.prefix
            environ['PATH_INFO'] = path_info[len(self.prefix):] or '/'
            print(f"Path adjusted: SCRIPT_NAME='{environ['SCRIPT_NAME']}', PATH_INFO='{environ['PATH_INFO']}'")
        
        # Special handling for static file requests
        elif path_info.startswith('/static'):
            # This might be a static file request without prefix
            environ['PATH_INFO'] = self.prefix + path_info
            print(f"Rewriting static path to: {environ['PATH_INFO']}")
        
        return self.wsgi_app(environ, start_response)
