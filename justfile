# List available commands
default:
    @just --list

# Build the Docker image
docker-build:
    docker build -t cursor-rules-bot .

# Run the Docker container with environment variables
docker-run:
    #!/usr/bin/env bash
    if [ ! -f .env ]; then
        echo "Error: .env file not found. Please create one with your GitHub App credentials:"
        echo "GITHUB_APP_ID=your_app_id"
        echo "GITHUB_PRIVATE_KEY=your_private_key"
        echo "WEBHOOK_SECRET=your_webhook_secret"
        exit 1
    fi
    docker run -p 8000:8000 --env-file .env cursor-rules-bot

# Build and run in one command
docker-start: docker-build docker-run

# List all test cases with their numbers
list-cases:
    #!/usr/bin/env python3
    import yaml
    from pathlib import Path
    
    test_dir = Path("tests/test_cases")
    for i, path in enumerate(sorted(test_dir.glob("*.yaml"))):
        with open(path) as f:
            data = yaml.safe_load(f)
            print(f"{i}: {data['name']} ({path.name})")

# Start the backend development server with hot reloading
start-backend:
    uvicorn app.main:app --reload

# Install frontend dependencies
install-frontend:
    cd frontend && npm install

# Start the frontend development server
start-frontend:
    cd frontend && npm run dev

# Start both frontend and backend (requires tmux)
start-dev:
    #!/usr/bin/env bash
    if ! command -v tmux &> /dev/null; then
        echo "tmux is required for running both servers. Please install tmux or run the servers separately:"
        echo "just start-backend"
        echo "just start-frontend"
        exit 1
    fi
    
    tmux new-session -d -s cursor-rules 'just start-backend'
    tmux split-window -h 'just start-frontend'
    tmux -2 attach-session -d

# Build the frontend
build-frontend:
    cd frontend && npm run build

# Run all tests
test:
    ./venv/bin/pytest tests/tests.py -v

# Run a specific test case by name
test-case name:
    ./venv/bin/pytest "tests/tests.py::tests[test_case{{name}}]" -v -s

# Run a specific test_prompts test case by name
test-prompts-case name:
    ./venv/bin/pytest "tests/tests.py::test_prompts[test_case{{name}}]" -v -s

# Run test with debug logging
test-debug n:
    ./venv/bin/pytest "tests/tests.py::tests[test_case{{n}}]" -v -s --log-cli-level=DEBUG 

# Run all format suggestion comment tests
test-format:
    ./venv/bin/pytest "tests/tests.py::test_format_suggestion_comment" -v -s

# Run a specific format suggestion test case by number
test-format-case n:
    ./venv/bin/pytest "tests/tests.py::test_format_suggestion_comment[test_case{{n}}]" -v -s 

# Run all merge test cases
test-merges:
    pytest tests/tests.py::test_merge_suggestions -v

# Run a specific merge test case by directory name
test-merge-case name:
    pytest "tests/tests.py::test_merge_case[{{name}}]" -v -s

# Run a specific apply test case by directory name
test-apply-case name:
    pytest "tests/tests.py::test_apply_changes[{{name}}]" -v -s

# List available merge test cases
list-merge-cases:
    #!/usr/bin/env python3
    from pathlib import Path
    
    merge_test_dir = Path("tests/merge_test_cases")
    if not merge_test_dir.exists():
        print("No merge test cases found")
        exit(0)
        
    print("\nAvailable merge test cases:")
    for case_dir in sorted(merge_test_dir.iterdir()):
        if case_dir.is_dir():
            print(f"- {case_dir.name}") 