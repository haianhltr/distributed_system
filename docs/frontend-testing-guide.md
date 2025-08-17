# Frontend Testing Guide for Multi-Operation System

## 🎯 Testing the New Operation Features

The dashboard has been updated to show and manage the new multi-operation functionality. Here's how to test it:

### 1. **Start the System**

```bash
# Terminal 1: Start main server
cd main_server
python main.py

# Terminal 2: Start dashboard
cd dashboard
python main.py

# Terminal 3: Start a bot
cd bots
python bot.py
```

### 2. **Access the Dashboard**

Open your browser and go to: `http://localhost:3002`

### 3. **What You Should See**

#### **New Bot Information:**
- **Operation Column**: Shows each bot's assigned operation or "unassigned"
- **Color-coded Operation Badges**: 
  - Blue: sum
  - Purple: subtract  
  - Green: multiply
  - Red: divide
  - Gray: unassigned

#### **New Job Information:**
- **Operation badges** on job cards showing the operation type
- **Correct operation symbols** (e.g., `123 * 456 = ...` instead of just `+`)
- **Operation column** in the recent jobs table

### 4. **Testing Operation Features**

#### **A. Create Jobs with Different Operations:**

1. Click **"Populate Jobs"** button
2. Enter number of jobs (e.g., 5)
3. **NEW**: Enter operation type (sum, subtract, multiply, divide)
4. Click OK - jobs will be created with that operation

#### **B. Assign Bots to Operations:**

1. Find a bot in the bots table
2. Click the **"Assign"** button next to the bot
3. **NEW**: Enter an operation (sum, subtract, multiply, divide) or leave empty to unassign
4. The bot will now only claim jobs of that operation type

#### **C. Test Dynamic Assignment:**

1. Make sure you have at least one **unassigned bot** (shows "unassigned" in Operation column)
2. Create jobs with different operations
3. Watch the unassigned bot claim a job and automatically get assigned to that operation
4. Refresh the page to see the bot's new assignment

### 5. **Expected Behavior**

#### **Assigned Bots:**
- Only show jobs matching their assigned operation
- Operation badge matches their assignment
- Will wait if no jobs of their type are available

#### **Unassigned Bots:**
- Show "unassigned" in the Operation column
- Will claim any available job (oldest first)
- Automatically get assigned to the operation of the job they claim
- Operation badge updates after assignment

#### **Job Processing:**
- Jobs now show correct mathematical results based on operation
- Job cards display operation badges
- Recent jobs table shows operation types

### 6. **Quick Test Scenarios**

#### **Scenario 1: Mixed Operations**
```
1. Create 3 sum jobs
2. Create 3 multiply jobs  
3. Assign one bot to "sum" only
4. Leave another bot unassigned
5. Watch how they claim different jobs
```

#### **Scenario 2: Dynamic Assignment**
```
1. Ensure all bots are unassigned
2. Create jobs: 2 subtract, 2 divide
3. Watch bots auto-assign to operations as they claim jobs
```

#### **Scenario 3: Operation Constraint**
```
1. Assign bot A to "multiply"
2. Create only "sum" jobs
3. Bot A should wait (not claim sum jobs)
4. Create multiply jobs
5. Bot A should immediately claim them
```

### 7. **Visual Indicators**

**Operation Badges Colors:**
- 🔵 **Blue**: sum operations
- 🟣 **Purple**: subtract operations  
- 🟢 **Green**: multiply operations
- 🔴 **Red**: divide operations
- ⚪ **Gray**: unassigned bots

**What Changed:**
- Bot table now has "Operation" column
- Job cards show operation type and correct math symbols
- "Populate Jobs" now asks for operation type
- New "Assign" button for each bot
- Job results calculated correctly per operation

### 8. **API Testing (Optional)**

You can also test the API directly:

```bash
# Get available operations
curl http://localhost:3001/operations

# Create jobs with specific operation
curl -X POST http://localhost:3001/jobs/populate \\
  -H "Authorization: Bearer admin-secret-token" \\
  -H "Content-Type: application/json" \\
  -d '{"batchSize": 3, "operation": "multiply"}'

# Assign bot to operation
curl -X POST http://localhost:3001/bots/bot-123/assign-operation \\
  -H "Authorization: Bearer admin-secret-token" \\
  -H "Content-Type: application/json" \\
  -d '{"operation": "subtract"}'

# Unassign bot
curl -X POST http://localhost:3001/bots/bot-123/assign-operation \\
  -H "Authorization: Bearer admin-secret-token" \\
  -H "Content-Type: application/json" \\
  -d '{"operation": null}'
```

### 9. **Troubleshooting**

**If you don't see operations:**
- Make sure the main server loaded the plugins (check server logs)
- Verify the dashboard is calling the updated API endpoints
- Refresh the browser to clear cache

**If bots aren't getting assigned:**
- Check that jobs exist for the bot's assigned operation
- Verify bots are running and sending heartbeats
- Look at server logs for claiming activity

**If operation badges don't show:**
- Check browser console for JavaScript errors
- Verify the template filters are working
- Make sure operation data is being returned by API

## 🎉 Success Criteria

You've successfully tested the multi-operation system when you can:

✅ See operation badges on bots and jobs  
✅ Create jobs with different operations via the UI  
✅ Assign bots to specific operations  
✅ Watch unassigned bots auto-assign to operations  
✅ See correct mathematical results for each operation type  
✅ Verify assigned bots only claim matching jobs  

The system is working correctly when the dashboard shows rich operation information and you can manage bot assignments through the web interface!