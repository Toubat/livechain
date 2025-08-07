"""
Asynchronous Coding Agent Example using Livechain

This example demonstrates how to build a comprehensive coding agent using Livechain's
event-driven architecture. The agent can:
- Generate code based on natural language requests
- Analyze and validate code for safety
- Execute code safely in isolated environments
- Perform file operations asynchronously
- Stream responses in real-time
- Manage reactive state changes

Key Features:
- Event-driven architecture with EventSignal classes
- Async file operations and subprocess management
- Code safety validation and sandboxing
- Real-time streaming via channels
- Reactive state management
- Comprehensive error handling
"""

import asyncio
import ast
import logging
import os
import re
import subprocess
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiofiles
from dotenv import find_dotenv, load_dotenv
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from livechain.graph.executor import Workflow
from livechain.graph.func import reactive, root, step, subscribe
from livechain.graph.ops import channel_send, channel_stream, get_state, mutate_state, trigger_workflow
from livechain.graph.types import EventSignal

# Load environment variables
load_dotenv(find_dotenv())

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Event Signal Classes
# ============================================================================

class CodeRequest(EventSignal):
    """Event signal for incoming code generation requests."""
    request_id: str = Field(..., description="Unique identifier for the request")
    prompt: str = Field(..., description="Natural language description of the code to generate")
    language: str = Field(default="python", description="Programming language for the code")
    context: Optional[str] = Field(default=None, description="Additional context or requirements")
    file_path: Optional[str] = Field(default=None, description="Optional file path to save the code")


class CodeResponse(EventSignal):
    """Event signal for generated code responses."""
    request_id: str = Field(..., description="ID of the original request")
    code: str = Field(..., description="Generated code")
    explanation: str = Field(..., description="Explanation of the generated code")
    language: str = Field(..., description="Programming language of the code")
    is_safe: bool = Field(..., description="Whether the code passed safety validation")
    safety_issues: List[str] = Field(default_factory=list, description="List of safety concerns if any")


class CodeExecutionRequest(EventSignal):
    """Event signal for code execution requests."""
    request_id: str = Field(..., description="Unique identifier for the execution request")
    code: str = Field(..., description="Code to execute")
    language: str = Field(default="python", description="Programming language")
    timeout: int = Field(default=30, description="Execution timeout in seconds")
    working_directory: Optional[str] = Field(default=None, description="Working directory for execution")


class ExecutionResult(EventSignal):
    """Event signal for code execution results."""
    request_id: str = Field(..., description="ID of the original execution request")
    success: bool = Field(..., description="Whether execution was successful")
    output: str = Field(default="", description="Standard output from execution")
    error: str = Field(default="", description="Error output if execution failed")
    execution_time: float = Field(..., description="Time taken for execution in seconds")


class FileOperationRequest(EventSignal):
    """Event signal for file operation requests."""
    request_id: str = Field(..., description="Unique identifier for the file operation")
    operation: str = Field(..., description="Type of operation: 'read', 'write', 'create', 'delete'")
    file_path: str = Field(..., description="Path to the file")
    content: Optional[str] = Field(default=None, description="Content for write operations")
    encoding: str = Field(default="utf-8", description="File encoding")


class FileOperationResult(EventSignal):
    """Event signal for file operation results."""
    request_id: str = Field(..., description="ID of the original file operation request")
    success: bool = Field(..., description="Whether the operation was successful")
    content: Optional[str] = Field(default=None, description="File content for read operations")
    error: Optional[str] = Field(default=None, description="Error message if operation failed")


# ============================================================================
# State Models
# ============================================================================

class CodingAgentState(BaseModel):
    """State model for the coding agent."""
    
    # Conversation and request tracking
    messages: List[AnyMessage] = Field(default_factory=list, description="Conversation history")
    active_requests: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Active code requests")
    completed_requests: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Completed requests")
    
    # Code management
    current_code: Optional[str] = Field(default=None, description="Currently generated code")
    code_language: str = Field(default="python", description="Current code language")
    code_files: Dict[str, str] = Field(default_factory=dict, description="Managed code files")
    
    # Execution and safety
    execution_status: str = Field(default="idle", description="Current execution status")
    safety_enabled: bool = Field(default=True, description="Whether safety checks are enabled")
    allowed_operations: Set[str] = Field(
        default_factory=lambda: {"file_read", "file_write", "code_generation", "safe_execution"},
        description="Set of allowed operations"
    )
    
    # Agent status
    agent_initialized: bool = Field(default=False, description="Whether the agent has been initialized")
    last_activity: Optional[datetime] = Field(default=None, description="Timestamp of last activity")
    error_count: int = Field(default=0, description="Number of errors encountered")
    
    # Performance metrics
    total_requests: int = Field(default=0, description="Total number of requests processed")
    successful_executions: int = Field(default=0, description="Number of successful code executions")
    failed_executions: int = Field(default=0, description="Number of failed code executions")


# ============================================================================
# Safety and Validation Utilities
# ============================================================================

class CodeSafetyValidator:
    """Utility class for validating code safety."""
    
    # Dangerous imports and functions to block
    DANGEROUS_IMPORTS = {
        'os', 'subprocess', 'sys', 'shutil', 'glob', 'socket', 'urllib',
        'requests', 'http', 'ftplib', 'smtplib', 'telnetlib', 'webbrowser',
        'ctypes', 'multiprocessing', 'threading', 'asyncio.subprocess'
    }
    
    DANGEROUS_FUNCTIONS = {
        'exec', 'eval', 'compile', '__import__', 'open', 'input', 'raw_input',
        'file', 'execfile', 'reload', 'vars', 'locals', 'globals', 'dir',
        'hasattr', 'getattr', 'setattr', 'delattr'
    }
    
    DANGEROUS_PATTERNS = [
        r'__.*__',  # Dunder methods
        r'\.system\(',  # System calls
        r'\.popen\(',  # Process opening
        r'\.call\(',  # Subprocess calls
        r'\.run\(',  # Subprocess run
    ]
    
    @classmethod
    def validate_code(cls, code: str, language: str = "python") -> tuple[bool, List[str]]:
        """
        Validate code for safety issues.
        
        Returns:
            tuple: (is_safe, list_of_issues)
        """
        issues = []
        
        if language.lower() != "python":
            # For non-Python languages, do basic pattern matching
            return cls._validate_non_python(code)
        
        try:
            # Parse the code to check for dangerous constructs
            tree = ast.parse(code)
            
            # Check for dangerous imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in cls.DANGEROUS_IMPORTS:
                            issues.append(f"Dangerous import detected: {alias.name}")
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module in cls.DANGEROUS_IMPORTS:
                        issues.append(f"Dangerous import detected: {node.module}")
                
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in cls.DANGEROUS_FUNCTIONS:
                            issues.append(f"Dangerous function call: {node.func.id}")
            
            # Check for dangerous patterns using regex
            for pattern in cls.DANGEROUS_PATTERNS:
                if re.search(pattern, code):
                    issues.append(f"Dangerous pattern detected: {pattern}")
            
        except SyntaxError as e:
            issues.append(f"Syntax error in code: {e}")
        except Exception as e:
            issues.append(f"Error parsing code: {e}")
        
        is_safe = len(issues) == 0
        return is_safe, issues
    
    @classmethod
    def _validate_non_python(cls, code: str) -> tuple[bool, List[str]]:
        """Validate non-Python code using pattern matching."""
        issues = []
        
        # Basic checks for potentially dangerous operations
        dangerous_keywords = [
            'system(', 'exec(', 'eval(', 'shell_exec', 'passthru',
            'rm -rf', 'del /f', 'format c:', 'dd if=', 'chmod 777'
        ]
        
        for keyword in dangerous_keywords:
            if keyword.lower() in code.lower():
                issues.append(f"Potentially dangerous operation: {keyword}")
        
        is_safe = len(issues) == 0
        return is_safe, issues


# ============================================================================
# Async Utilities
# ============================================================================

@asynccontextmanager
async def safe_temp_directory():
    """Create a temporary directory for safe code execution."""
    temp_dir = tempfile.mkdtemp(prefix="coding_agent_")
    try:
        yield temp_dir
    finally:
        # Clean up the temporary directory
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


async def execute_code_safely(
    code: str, 
    language: str = "python", 
    timeout: int = 30,
    working_dir: Optional[str] = None
) -> tuple[bool, str, str, float]:
    """
    Execute code safely in a subprocess with timeout.
    
    Returns:
        tuple: (success, stdout, stderr, execution_time)
    """
    start_time = asyncio.get_event_loop().time()
    
    try:
        if language.lower() == "python":
            # Create a temporary file for the Python code
            async with safe_temp_directory() as temp_dir:
                code_file = Path(temp_dir) / "code.py"
                
                async with aiofiles.open(code_file, 'w') as f:
                    await f.write(code)
                
                # Execute the Python code
                process = await asyncio.create_subprocess_exec(
                    'python', str(code_file),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir or temp_dir
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=timeout
                    )
                    
                    execution_time = asyncio.get_event_loop().time() - start_time
                    success = process.returncode == 0
                    
                    return (
                        success,
                        stdout.decode('utf-8', errors='replace'),
                        stderr.decode('utf-8', errors='replace'),
                        execution_time
                    )
                    
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    execution_time = asyncio.get_event_loop().time() - start_time
                    return False, "", f"Execution timed out after {timeout} seconds", execution_time
        
        else:
            # For other languages, return an error
            execution_time = asyncio.get_event_loop().time() - start_time
            return False, "", f"Language '{language}' not supported for execution", execution_time
    
    except Exception as e:
        execution_time = asyncio.get_event_loop().time() - start_time
        return False, "", f"Execution error: {str(e)}", execution_time


# ============================================================================
# Workflow Steps
# ============================================================================

@step()
async def initialize_agent():
    """Initialize the coding agent with system prompt and configuration."""
    state = get_state(CodingAgentState)
    
    if state.agent_initialized:
        return
    
    system_message = SystemMessage(
        content=(
            "You are an advanced coding assistant powered by Livechain. "
            "You can generate, analyze, and execute code safely. "
            "You have access to file operations and can work with multiple programming languages. "
            "Always prioritize code safety and provide clear explanations. "
            "When generating code, consider best practices and potential security implications."
        )
    )
    
    await mutate_state(
        messages=[system_message],
        agent_initialized=True,
        last_activity=datetime.now()
    )
    
    logger.info("Coding agent initialized successfully")


@step()
async def generate_code(request: CodeRequest):
    """Generate code based on the request using ChatOpenAI."""
    state = get_state(CodingAgentState)
    
    # Create a detailed prompt for code generation
    prompt = f"""
    Generate {request.language} code for the following request:
    
    Request: {request.prompt}
    
    Additional Context: {request.context or 'None'}
    
    Please provide:
    1. Clean, well-commented code
    2. A brief explanation of what the code does
    3. Any important considerations or limitations
    
    Focus on writing safe, efficient, and maintainable code.
    """
    
    user_message = HumanMessage(content=prompt)
    messages = state.messages + [user_message]
    
    # Use ChatOpenAI to generate the code
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    
    try:
        # Stream the response for real-time feedback
        async with channel_stream("code_generation") as stream_send:
            await stream_send(f"🔄 Generating {request.language} code for request: {request.request_id}")
            
            response = await llm.ainvoke(messages)
            
            # Extract code and explanation from the response
            response_content = response.content
            
            # Simple parsing to separate code from explanation
            # This is a basic implementation - in practice, you might want more sophisticated parsing
            code_blocks = re.findall(r'```(?:\w+)?\n(.*?)\n```', response_content, re.DOTALL)
            
            if code_blocks:
                generated_code = code_blocks[0].strip()
            else:
                # If no code blocks found, treat the entire response as code
                generated_code = response_content.strip()
            
            # Validate code safety
            is_safe, safety_issues = CodeSafetyValidator.validate_code(
                generated_code, request.language
            )
            
            # Create response event
            code_response = CodeResponse(
                request_id=request.request_id,
                code=generated_code,
                explanation=response_content,
                language=request.language,
                is_safe=is_safe,
                safety_issues=safety_issues
            )
            
            # Update state
            await mutate_state(
                messages=messages + [response],
                current_code=generated_code,
                code_language=request.language,
                total_requests=state.total_requests + 1,
                last_activity=datetime.now()
            )
            
            await stream_send(f"✅ Code generation completed for request: {request.request_id}")
            
            # Publish the code response event
            from livechain.graph.ops import publish_event
            await publish_event(code_response)
            
    except Exception as e:
        logger.error(f"Error generating code for request {request.request_id}: {e}")
        
        error_response = CodeResponse(
            request_id=request.request_id,
            code="",
            explanation=f"Error generating code: {str(e)}",
            language=request.language,
            is_safe=False,
            safety_issues=[f"Generation error: {str(e)}"]
        )
        
        await mutate_state(error_count=state.error_count + 1)
        
        from livechain.graph.ops import publish_event
        await publish_event(error_response)


@step()
async def analyze_code(code: str, language: str = "python") -> Dict[str, Any]:
    """Analyze code for complexity, safety, and quality metrics."""
    
    analysis_result = {
        "language": language,
        "line_count": len(code.split('\n')),
        "character_count": len(code),
        "safety_check": {},
        "complexity_metrics": {},
        "suggestions": []
    }
    
    # Safety analysis
    is_safe, safety_issues = CodeSafetyValidator.validate_code(code, language)
    analysis_result["safety_check"] = {
        "is_safe": is_safe,
        "issues": safety_issues
    }
    
    if language.lower() == "python":
        try:
            # Parse AST for Python-specific analysis
            tree = ast.parse(code)
            
            # Count different node types
            node_counts = {}
            for node in ast.walk(tree):
                node_type = type(node).__name__
                node_counts[node_type] = node_counts.get(node_type, 0) + 1
            
            analysis_result["complexity_metrics"] = {
                "ast_nodes": node_counts,
                "function_count": node_counts.get("FunctionDef", 0),
                "class_count": node_counts.get("ClassDef", 0),
                "import_count": node_counts.get("Import", 0) + node_counts.get("ImportFrom", 0)
            }
            
            # Generate suggestions based on analysis
            if node_counts.get("FunctionDef", 0) == 0 and analysis_result["line_count"] > 10:
                analysis_result["suggestions"].append("Consider breaking code into functions for better organization")
            
            if not any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) 
                      and isinstance(node.value.value, str) for node in ast.walk(tree)):
                analysis_result["suggestions"].append("Consider adding docstrings for better documentation")
                
        except SyntaxError:
            analysis_result["complexity_metrics"]["syntax_error"] = True
            analysis_result["suggestions"].append("Fix syntax errors before execution")
    
    return analysis_result


# ============================================================================
# File Operations
# ============================================================================

@step()
async def handle_file_operation(request: FileOperationRequest):
    """Handle file operations asynchronously."""
    
    try:
        if request.operation == "read":
            async with aiofiles.open(request.file_path, 'r', encoding=request.encoding) as f:
                content = await f.read()
            
            result = FileOperationResult(
                request_id=request.request_id,
                success=True,
                content=content
            )
        
        elif request.operation == "write":
            # Ensure directory exists
            os.makedirs(os.path.dirname(request.file_path), exist_ok=True)
            
            async with aiofiles.open(request.file_path, 'w', encoding=request.encoding) as f:
                await f.write(request.content or "")
            
            result = FileOperationResult(
                request_id=request.request_id,
                success=True
            )
        
        elif request.operation == "create":
            if os.path.exists(request.file_path):
                result = FileOperationResult(
                    request_id=request.request_id,
                    success=False,
                    error="File already exists"
                )
            else:
                # Ensure directory exists
                os.makedirs(os.path.dirname(request.file_path), exist_ok=True)
                
                async with aiofiles.open(request.file_path, 'w', encoding=request.encoding) as f:
                    await f.write(request.content or "")
                
                result = FileOperationResult(
                    request_id=request.request_id,
                    success=True
                )
        
        elif request.operation == "delete":
            if os.path.exists(request.file_path):
                os.remove(request.file_path)
                result = FileOperationResult(
                    request_id=request.request_id,
                    success=True
                )
            else:
                result = FileOperationResult(
                    request_id=request.request_id,
                    success=False,
                    error="File does not exist"
                )
        
        else:
            result = FileOperationResult(
                request_id=request.request_id,
                success=False,
                error=f"Unknown operation: {request.operation}"
            )
        
        # Publish the result
        from livechain.graph.ops import publish_event
        await publish_event(result)
        
    except Exception as e:
        logger.error(f"File operation error: {e}")
        
        error_result = FileOperationResult(
            request_id=request.request_id,
            success=False,
            error=str(e)
        )
        
        from livechain.graph.ops import publish_event
        await publish_event(error_result)


# ============================================================================
# Event Subscribers
# ============================================================================

@subscribe(CodeRequest)
async def handle_code_request(event: CodeRequest):
    """Handle incoming code generation requests."""
    state = get_state(CodingAgentState)
    
    logger.info(f"Received code request: {event.request_id}")
    
    # Track the active request
    await mutate_state(
        active_requests={
            **state.active_requests,
            event.request_id: {
                "prompt": event.prompt,
                "language": event.language,
                "timestamp": datetime.now().isoformat(),
                "status": "processing"
            }
        }
    )
    
    # Generate the code
    await generate_code(event)


@subscribe(CodeExecutionRequest)
async def handle_code_execution(event: CodeExecutionRequest):
    """Handle code execution requests."""
    state = get_state(CodingAgentState)
    
    logger.info(f"Executing code for request: {event.request_id}")
    
    await mutate_state(execution_status="executing")
    
    try:
        # Validate code safety first
        is_safe, safety_issues = CodeSafetyValidator.validate_code(event.code, event.language)
        
        if not is_safe and state.safety_enabled:
            result = ExecutionResult(
                request_id=event.request_id,
                success=False,
                error=f"Code execution blocked due to safety issues: {', '.join(safety_issues)}",
                execution_time=0.0
            )
        else:
            # Execute the code
            success, stdout, stderr, exec_time = await execute_code_safely(
                event.code,
                event.language,
                event.timeout,
                event.working_directory
            )
            
            result = ExecutionResult(
                request_id=event.request_id,
                success=success,
                output=stdout,
                error=stderr,
                execution_time=exec_time
            )
        
        # Update execution statistics
        if result.success:
            await mutate_state(
                successful_executions=state.successful_executions + 1,
                execution_status="completed"
            )
        else:
            await mutate_state(
                failed_executions=state.failed_executions + 1,
                execution_status="failed"
            )
        
        # Publish execution result
        from livechain.graph.ops import publish_event
        await publish_event(result)
        
    except Exception as e:
        logger.error(f"Error executing code: {e}")
        
        error_result = ExecutionResult(
            request_id=event.request_id,
            success=False,
            error=f"Execution error: {str(e)}",
            execution_time=0.0
        )
        
        await mutate_state(
            failed_executions=state.failed_executions + 1,
            execution_status="error"
        )
        
        from livechain.graph.ops import publish_event
        await publish_event(error_result)


@subscribe(FileOperationRequest)
async def handle_file_request(event: FileOperationRequest):
    """Handle file operation requests."""
    logger.info(f"Processing file operation: {event.operation} on {event.file_path}")
    await handle_file_operation(event)


# ============================================================================
# Reactive Handlers
# ============================================================================

@reactive(CodingAgentState, lambda state: state.execution_status)
async def on_execution_status_change(old_state: CodingAgentState, new_state: CodingAgentState):
    """React to execution status changes."""
    if old_state.execution_status != new_state.execution_status:
        logger.info(f"Execution status changed: {old_state.execution_status} -> {new_state.execution_status}")
        
        await channel_send("status_updates", {
            "type": "execution_status",
            "old_status": old_state.execution_status,
            "new_status": new_state.execution_status,
            "timestamp": datetime.now().isoformat()
        })


@reactive(CodingAgentState, lambda state: state.error_count)
async def on_error_count_change(old_state: CodingAgentState, new_state: CodingAgentState):
    """React to error count changes."""
    if new_state.error_count > old_state.error_count:
        logger.warning(f"Error count increased to: {new_state.error_count}")
        
        await channel_send("status_updates", {
            "type": "error_count",
            "error_count": new_state.error_count,
            "timestamp": datetime.now().isoformat()
        })


@reactive(CodingAgentState, lambda state: len(state.active_requests))
async def on_active_requests_change(old_state: CodingAgentState, new_state: CodingAgentState):
    """React to changes in active requests."""
    old_count = len(old_state.active_requests)
    new_count = len(new_state.active_requests)
    
    if old_count != new_count:
        logger.info(f"Active requests changed: {old_count} -> {new_count}")
        
        await channel_send("status_updates", {
            "type": "active_requests",
            "count": new_count,
            "requests": list(new_state.active_requests.keys()),
            "timestamp": datetime.now().isoformat()
        })


# ============================================================================
# Root Workflow
# ============================================================================

@root()
async def coding_agent_entrypoint():
    """Main entrypoint for the coding agent workflow."""
    logger.info("Starting Coding Agent workflow...")
    
    # Initialize the agent
    await initialize_agent()
    
    # Send initial status
    await channel_send("agent_status", {
        "status": "ready",
        "message": "Coding agent is ready to process requests",
        "timestamp": datetime.now().isoformat()
    })
    
    # Keep the workflow running
    while True:
        state = get_state(CodingAgentState)
        
        # Update last activity timestamp periodically
        await mutate_state(last_activity=datetime.now())
        
        # Wait before next iteration
        await asyncio.sleep(1)


# ============================================================================
# Workflow Compilation
# ============================================================================

# Create the workflow
workflow = Workflow.from_routines(
    root=coding_agent_entrypoint,
    routines=[
        handle_code_request,
        handle_code_execution,
        handle_file_request,
        on_execution_status_change,
        on_error_count_change,
        on_active_requests_change,
    ]
)

# Compile the workflow
executor = workflow.compile(CodingAgentState)


# ============================================================================
# Example Usage and Main Function
# ============================================================================

async def main():
    """
    Example usage of the asynchronous coding agent.
    
    This demonstrates:
    - Starting the workflow executor
    - Publishing various code request events
    - Handling streaming responses via channel receivers
    - Managing the agent lifecycle with proper cleanup
    - Showcasing different coding scenarios
    """
    
    # Set up channel receivers for real-time feedback
    @executor.recv("code_generation")
    async def handle_code_generation_updates(message: str):
        print(f"🔄 Code Generation: {message}")
    
    @executor.recv("agent_status")
    async def handle_agent_status(status_data: Dict[str, Any]):
        print(f"🤖 Agent Status: {status_data['message']}")
    
    @executor.recv("status_updates")
    async def handle_status_updates(update_data: Dict[str, Any]):
        print(f"📊 Status Update: {update_data}")
    
    # Start the executor
    print("🚀 Starting Coding Agent...")
    executor.start()
    
    # Wait for agent to initialize
    await asyncio.sleep(2)
    
    try:
        # Example 1: Simple Python code generation
        print("\n" + "="*60)
        print("Example 1: Generate a simple Python function")
        print("="*60)
        
        code_request_1 = CodeRequest(
            request_id="req_001",
            prompt="Create a function that calculates the factorial of a number using recursion",
            language="python",
            context="The function should handle edge cases and include proper documentation"
        )
        
        await executor.publish_event(code_request_1)
        await asyncio.sleep(5)  # Wait for processing
        
        # Example 2: Code execution
        print("\n" + "="*60)
        print("Example 2: Execute generated code")
        print("="*60)
        
        sample_code = """
def factorial(n):
    '''Calculate factorial of n using recursion.'''
    if n < 0:
        raise ValueError("Factorial is not defined for negative numbers")
    elif n == 0 or n == 1:
        return 1
    else:
        return n * factorial(n - 1)

# Test the function
print("Factorial of 5:", factorial(5))
print("Factorial of 0:", factorial(0))
"""
        
        execution_request = CodeExecutionRequest(
            request_id="exec_001",
            code=sample_code,
            language="python",
            timeout=10
        )
        
        await executor.publish_event(execution_request)
        await asyncio.sleep(3)  # Wait for execution
        
        # Example 3: File operations
        print("\n" + "="*60)
        print("Example 3: File operations")
        print("="*60)
        
        # Create a temporary file
        temp_file_path = "/tmp/coding_agent_example.py"
        
        file_write_request = FileOperationRequest(
            request_id="file_001",
            operation="write",
            file_path=temp_file_path,
            content=sample_code
        )
        
        await executor.publish_event(file_write_request)
        await asyncio.sleep(1)
        
        # Read the file back
        file_read_request = FileOperationRequest(
            request_id="file_002",
            operation="read",
            file_path=temp_file_path
        )
        
        await executor.publish_event(file_read_request)
        await asyncio.sleep(1)
        
        # Example 4: Complex code generation with context
        print("\n" + "="*60)
        print("Example 4: Complex code generation with context")
        print("="*60)
        
        complex_request = CodeRequest(
            request_id="req_002",
            prompt="Create a class for managing a simple in-memory cache with TTL (time-to-live) support",
            language="python",
            context=(
                "The cache should support get, set, delete operations. "
                "Items should automatically expire after their TTL. "
                "Include proper error handling and type hints."
            )
        )
        
        await executor.publish_event(complex_request)
        await asyncio.sleep(8)  # Wait for processing
        
        # Example 5: Demonstrate safety validation
        print("\n" + "="*60)
        print("Example 5: Safety validation (this should be blocked)")
        print("="*60)
        
        unsafe_code = """
import os
import subprocess

# This code should be blocked by safety validation
os.system("rm -rf /")
subprocess.call(["dangerous_command"])
"""
        
        unsafe_execution = CodeExecutionRequest(
            request_id="unsafe_001",
            code=unsafe_code,
            language="python"
        )
        
        await executor.publish_event(unsafe_execution)
        await asyncio.sleep(2)
        
        print("\n" + "="*60)
        print("Examples completed! Check the output above for results.")
        print("="*60)
        
        # Keep running for a bit to see all responses
        await asyncio.sleep(5)
        
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    
    finally:
        # Clean up
        print("🧹 Cleaning up...")
        await executor.stop()
        print("✅ Coding Agent stopped successfully")


if __name__ == "__main__":
    """
    Run the coding agent example.
    
    Make sure you have:
    1. Set up your OpenAI API key in environment variables
    2. Installed required dependencies: livechain, langchain-openai, aiofiles
    3. Python 3.12+ installed
    
    Usage:
        python async_coding_agent.py
    """
    
    print("🤖 Asynchronous Coding Agent Example")
    print("=" * 50)
    print("This example demonstrates a comprehensive coding agent built with Livechain.")
    print("The agent can generate, analyze, execute code, and perform file operations.")
    print("All operations are performed asynchronously with proper safety measures.")
    print("=" * 50)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Error running example: {e}")
        logger.exception("Error in main execution")
