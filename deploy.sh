#!/bin/bash

# SafeSphere Production Deployment Script
# Usage: ./deploy.sh [start|stop|restart|update|backup|logs]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_NAME="safesphere"
COMPOSE_FILE="docker-compose.prod.yml"
BACKUP_DIR="./backups"
LOG_DIR="./logs"

# Create necessary directories
mkdir -p $BACKUP_DIR $LOG_DIR nginx/ssl

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        print_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
}

# Function to check if .env.prod exists
check_env() {
    if [ ! -f .env.prod ]; then
        print_error ".env.prod file not found. Please create it from env.example"
        exit 1
    fi
}

# Function to backup database
backup_database() {
    print_status "Creating database backup..."

    # Get database credentials from environment
    source .env.prod

    # Create backup using pg_dump with external database
    pg_dump "postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME" > $BACKUP_DIR/backup_$(date +%Y%m%d_%H%M%S).sql
    print_status "Backup completed successfully"
}

# Function to start services
start_services() {
    print_status "Starting SafeSphere services..."
    docker-compose -f $COMPOSE_FILE up -d
    print_status "Services started successfully"
}

# Function to stop services
stop_services() {
    print_status "Stopping SafeSphere services..."
    docker-compose -f $COMPOSE_FILE down
    print_status "Services stopped successfully"
}

# Function to restart services
restart_services() {
    print_status "Restarting SafeSphere services..."
    docker-compose -f $COMPOSE_FILE restart
    print_status "Services restarted successfully"
}

# Function to update and restart services
update_services() {
    print_status "Updating SafeSphere services..."
    
    # Pull latest changes
    git pull origin main
    
    # Build new images
    docker-compose -f $COMPOSE_FILE build --no-cache
    
    # Stop services
    stop_services
    
    # Start services
    start_services
    
    # Run migrations
    docker-compose -f $COMPOSE_FILE exec -T backend python manage.py migrate
    
    # Collect static files
    docker-compose -f $COMPOSE_FILE exec -T backend python manage.py collectstatic --noinput
    
    print_status "Update completed successfully"
}

# Function to show logs
show_logs() {
    if [ -z "$2" ]; then
        docker-compose -f $COMPOSE_FILE logs -f
    else
        docker-compose -f $COMPOSE_FILE logs -f $2
    fi
}

# Function to check service health
check_health() {
    print_status "Checking service health..."
    
    # Check if services are running
    if docker-compose -f $COMPOSE_FILE ps | grep -q "Up"; then
        print_status "All services are running"
    else
        print_error "Some services are not running"
        docker-compose -f $COMPOSE_FILE ps
    fi
    
    # Check nginx health
    if curl -f http://localhost/health > /dev/null 2>&1; then
        print_status "Nginx is responding"
    else
        print_error "Nginx is not responding"
    fi
}

# Function to setup SSL certificates
setup_ssl() {
    print_status "Setting up SSL certificates..."
    
    if [ ! -f nginx/ssl/cert.pem ] || [ ! -f nginx/ssl/key.pem ]; then
        print_warning "SSL certificates not found. Creating self-signed certificates for development..."
        mkdir -p nginx/ssl
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout nginx/ssl/key.pem \
            -out nginx/ssl/cert.pem \
            -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"
        print_status "Self-signed certificates created"
    else
        print_status "SSL certificates already exist"
    fi
}

# Function to initialize database
init_database() {
    print_status "Initializing database..."
    
    # Run migrations
    docker-compose -f $COMPOSE_FILE exec -T backend python manage.py migrate
    
    # Create superuser if it doesn't exist
    docker-compose -f $COMPOSE_FILE exec -T backend python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    print('Superuser created: admin/admin123')
else:
    print('Superuser already exists')
"
    
    # Collect static files
    docker-compose -f $COMPOSE_FILE exec -T backend python manage.py collectstatic --noinput
    
    print_status "Database initialization completed"
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start     - Start all services"
    echo "  stop      - Stop all services"
    echo "  restart   - Restart all services"
    echo "  update    - Update and restart services"
    echo "  backup    - Create database backup"
    echo "  logs      - Show logs (all or specific service)"
    echo "  health    - Check service health"
    echo "  ssl       - Setup SSL certificates"
    echo "  init      - Initialize database"
    echo "  help      - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 logs backend"
    echo "  $0 backup"
}

# Main script logic
case "$1" in
    start)
        check_docker
        check_env
        setup_ssl
        start_services
        print_status "SafeSphere is starting up..."
        print_status "Check logs with: $0 logs"
        ;;
    stop)
        check_docker
        stop_services
        ;;
    restart)
        check_docker
        restart_services
        ;;
    update)
        check_docker
        check_env
        backup_database
        update_services
        ;;
    backup)
        check_docker
        backup_database
        ;;
    logs)
        check_docker
        show_logs $@
        ;;
    health)
        check_docker
        check_health
        ;;
    ssl)
        setup_ssl
        ;;
    init)
        check_docker
        check_env
        init_database
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        print_error "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac 
