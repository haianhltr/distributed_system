# UML Diagrams for Distributed Job Processing System

This directory contains comprehensive UML diagrams that document the architecture and behavior of the distributed job processing system.

## Diagrams Overview

### 1. **Class Diagram** (`class_diagram.puml`)
Shows the main classes, their attributes, methods, and relationships in the system.

**Key Components:**
- **Main Server**: FastAPI application, database manager, datalake manager
- **Services**: Job service, bot service, monitoring service, metrics service
- **Operations**: Abstract operation interface and concrete implementations (sum, subtract, multiply, divide)
- **Models**: Pydantic schemas for request/response validation
- **Database Schema**: Core tables (jobs, bots, results)

**Use Case**: Understanding the system's object-oriented structure and dependencies.

### 2. **Sequence Diagram** (`sequence_diagram.puml`)
Illustrates the complete job processing workflow from creation to completion.

**Workflow Steps:**
1. **Job Creation**: Admin creates batch of jobs
2. **Bot Registration**: Worker bot registers with system
3. **Operation Assignment**: Bot gets assigned specific operation type
4. **Job Claiming**: Bot claims available job matching its operation
5. **Job Processing**: Bot executes operation and reports results
6. **Heartbeat Monitoring**: Continuous health monitoring
7. **Cleanup & Recovery**: Background tasks for system maintenance

**Use Case**: Understanding the dynamic interactions between system components.

### 3. **Component Diagram** (`component_diagram.puml`)
Shows the high-level system architecture and component interactions.

**Architecture Layers:**
- **External Systems**: Worker bots, admin dashboard, monitoring tools
- **API Gateway**: FastAPI server with middleware
- **Core Services**: Business logic services
- **Data Layer**: Database and file system management
- **Operations Engine**: Pluggable operation implementations
- **Background Tasks**: Automated system maintenance
- **Utilities**: Logging, error handling, configuration

**Use Case**: Understanding the system's overall architecture and component relationships.

### 4. **Job State Diagram** (`state_diagram.puml`)
Models the lifecycle states of a job through the system.

**Job States:**
- **Pending**: Available for bot assignment
- **Claimed**: Bot has claimed but not started
- **Processing**: Bot is actively executing
- **Succeeded**: Job completed successfully
- **Failed**: Job failed (with retry logic)

**Use Case**: Understanding job lifecycle and state transitions.

### 5. **Bot State Diagram** (`bot_state_diagram.puml`)
Models the lifecycle states of worker bots.

**Bot States:**
- **Unregistered**: Bot exists but unknown to system
- **Registered**: Bot can claim jobs
- **Idle**: Available for job assignment
- **Busy**: Processing a job
- **Down**: Not responding to heartbeats
- **Deleted**: Marked for removal

**Use Case**: Understanding bot lifecycle and health monitoring.

### 6. **Deployment Diagram** (`deployment_diagram.puml`)
Shows how the system is deployed across containers and infrastructure.

**Deployment Components:**
- **Main Server Container**: Core application services
- **PostgreSQL Container**: Database
- **Dashboard Container**: Web interface
- **External Bots**: Worker processes
- **File System**: Data lake and logs

**Use Case**: Understanding system deployment and infrastructure requirements.

## How to Use These Diagrams

### **For Developers:**
- Use **Class Diagram** to understand code structure and relationships
- Use **Sequence Diagram** to understand API workflows
- Use **Component Diagram** to understand system architecture

### **For DevOps/Operations:**
- Use **Deployment Diagram** to understand infrastructure requirements
- Use **Component Diagram** to understand service dependencies
- Use **State Diagrams** to understand monitoring requirements

### **For System Design:**
- Use **Component Diagram** to understand system boundaries
- Use **State Diagrams** to understand system behavior
- Use **Sequence Diagram** to understand integration points

## Tools for Viewing

These diagrams are written in **PlantUML** format and can be viewed using:

1. **PlantUML Extension** in VS Code
2. **PlantUML Online Server**: http://www.plantuml.com/plantuml/
3. **PlantUML Desktop Application**
4. **IntelliJ IDEA** with PlantUML plugin

## Generating Images

To generate PNG/SVG images from these diagrams:

```bash
# Using PlantUML JAR
java -jar plantuml.jar *.puml

# Using PlantUML Python package
pip install plantuml
python -m plantuml *.puml
```

## System Architecture Summary

The distributed job processing system follows a **microservices architecture** with:

- **RESTful API** for external communication
- **Service-oriented design** for business logic
- **Plugin architecture** for operations
- **Event-driven processing** for background tasks
- **Fault-tolerant design** with automatic recovery
- **Containerized deployment** for scalability

The system demonstrates key distributed computing patterns:
- **Leader election** (job distribution)
- **Circuit breaker** (fault tolerance)
- **Event sourcing** (job lifecycle tracking)
- **CQRS** (command/query separation)
- **Saga pattern** (distributed transactions)
