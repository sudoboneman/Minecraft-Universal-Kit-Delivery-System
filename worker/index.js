require('dotenv').config()

const mineflayer = require('mineflayer')
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder')
const express = require('express')
const fs = require('fs')

function envStr(name, defVal) { return process.env[name] || defVal }
function envInt(name, defVal) { return parseInt(process.env[name]) || defVal }

const sleep = ms => new Promise(r => setTimeout(r, ms))

const CONFIG = {
  host: envStr('MC_HOST', 'play.6b6t.org'),
  port: envInt('MC_PORT', 25565),
  auth: envStr('MC_AUTH', 'offline'),
  version: envStr('MC_VERSION', '1.20.1'),
  worker: { username: envStr('WORKER_USERNAME', 'workerbot'), password: envStr('WORKER_PASSWORD', 'password') },
  apiPort: envInt('API_PORT', 3003)
}

const kitsConfig = JSON.parse(fs.readFileSync('./kits.json', 'utf8'))
const app = express()
app.use(express.json())

let orderQueue = []
let failedOrders = []
let isProcessingQueue = false
let workerReady = false
let isFirstSpawn = true
let playerBot = null
let mcData = null

const FAILED_ORDERS_FILE = './failed_orders.json'

if (fs.existsSync(FAILED_ORDERS_FILE)) {
  try {
    failedOrders = JSON.parse(fs.readFileSync(FAILED_ORDERS_FILE, 'utf8'))
    console.log(`[System] Loaded ${failedOrders.length} pending refunds from disk.`)
  } catch (err) {
    console.error('[System] Error reading failed_orders.json:', err.message)
  }
}

function saveFailedOrders() {
  try {
    fs.writeFileSync(FAILED_ORDERS_FILE, JSON.stringify(failedOrders, null, 2))
  } catch (err) {
    console.error('[System] Failed to save to failed_orders.json:', err.message)
  }
}

app.get('/kits', (req, res) => res.json(Object.fromEntries(Object.entries(kitsConfig).map(([k, v]) => [k, { price: v.price }]))))
app.get('/failed_orders', (req, res) => res.json(failedOrders))

app.post('/clear_failed', (req, res) => {
  const { id } = req.body
  failedOrders = failedOrders.filter(o => o.id !== id)
  saveFailedOrders() 
  res.sendStatus(200)
})

app.post('/send_verify', (req, res) => {
  const { ign, code } = req.body
  // added playerBot.entity check to ensure it isn't currently dead
  if (!workerReady || !playerBot || !playerBot.entity) {
    return res.status(503).json({ error: 'bot offline or dead' })
  }
  playerBot.chat(`/w ${ign} your verification code: ${code}`)
  res.json({ success: true })
})

app.post('/order', (req, res) => { 
  orderQueue.push(req.body)
  res.json({ queuePosition: orderQueue.length })
  
  if (!isProcessingQueue) {
    processQueueLoop()
  }
})

app.listen(CONFIG.apiPort, () => console.log(`API on port ${CONFIG.apiPort}`))

function startWorkerBot() {
  playerBot = mineflayer.createBot({ host: CONFIG.host, port: CONFIG.port, username: CONFIG.worker.username, auth: CONFIG.auth, version: CONFIG.version })
  playerBot.loadPlugin(pathfinder)

  playerBot.on('spawn', () => {
    console.log(`[Worker] ${playerBot.username} spawned`)
    mcData = require('minecraft-data')(playerBot.version)

    if (isFirstSpawn) {
      isFirstSpawn = false
      
      if (CONFIG.auth === 'offline') {
        //OFFLINE ACCOUNT LOGIC
        playerBot.chat(`/login ${CONFIG.worker.password}`)
        setTimeout(() => {
          playerBot.setControlState('forward', true)
          playerBot.setControlState('sprint', true)
          playerBot.setControlState('jump', true)
          setTimeout(() => {
            playerBot.clearControlStates()
            if (playerBot && playerBot.entity) {
              workerReady = true
              console.log('[worker] fully loaded and ready for operations.')
            }
          }, 10000) // Long 10-second sprint
        }, 3000) // 3-second wait for AuthMe to prompt
        
      } else {
        //ONLINE ACCOUNT LOGIC
        // Skips /login completely
        setTimeout(() => {
          playerBot.setControlState('forward', true)
          playerBot.setControlState('sprint', true)
          playerBot.setControlState('jump', true)
          setTimeout(() => {
            playerBot.clearControlStates()
            if (playerBot && playerBot.entity) {
              workerReady = true
              console.log('[worker] fully loaded (online mode) and ready for operations.')
            }
          }, 5000) // Reduced 5-second sprint
        }, 3000) // Reduced 3-second wait before running
      }
      
    } else {
      workerReady = true
      console.log('[Worker] Respawned and ready.')
    }
  })

  playerBot.on('death', () => {
    console.log('[Worker] Died. Waiting to respawn...')
    workerReady = false
    setTimeout(() => {
      if (playerBot) playerBot.respawn()
    }, 5000)
  })

  playerBot.on('kicked', r => console.log('[Worker] Kicked:', r))
  playerBot.on('error', e => console.log('[Worker] Error:', e.message))
  
  playerBot.on('end', () => {
    console.log('[Worker] Disconnected from server. Reconnecting in 15s...')
    workerReady = false
    isFirstSpawn = true
    setTimeout(startWorkerBot, 15000)
  })
}

function failOrder(order, reason) {
  console.log(`[Worker] Order Failed (${reason}). Queueing refund for ${order.ign}.`)
  failedOrders.push({
    'id': order.id || 'unknown',
    'discord_id': order.discord_id || '',
    'ign': order.ign,
    'refund_amount': order.refund_amount || 0
  })
  saveFailedOrders()
}

function checkPlayerNearby(ign) {
  if (!playerBot || !playerBot.players) return false
  const target = playerBot.players[ign]
  if (!target || !target.entity || !playerBot.entity) return false
  
  const dx = playerBot.entity.position.x - target.entity.position.x
  const dy = playerBot.entity.position.y - target.entity.position.y
  const dz = playerBot.entity.position.z - target.entity.position.z
  const dist = Math.sqrt(dx*dx + dy*dy + dz*dz)
  
  return dist < 50
}

async function waitForPlayerToAcceptTPA(ign, timeoutSeconds = 120) {
  return new Promise((resolve, reject) => {
    let secondsWaited = 0;

    const interval = setInterval(() => {

      if (!workerReady || !playerBot || !playerBot.entity) {
        clearInterval(interval)
        return reject(new Error('Bot disconnected or died while waiting for TPA'))
      }

      if (checkPlayerNearby(ign)) {
        clearInterval(interval)
        return resolve()
      }

      secondsWaited++
      if (secondsWaited >= timeoutSeconds) {
        clearInterval(interval)
        return reject(new Error('TPA Acceptance Timeout'))
      }
    }, 1000)
  })
}

async function processQueueLoop() {
  if (isProcessingQueue) return
  isProcessingQueue = true

  while (orderQueue.length > 0) {
    while (!workerReady || !playerBot || !playerBot.entity) {
      await sleep(2000) 
    }

    const currentOrder = orderQueue[0]
    const kit = kitsConfig[currentOrder.kit]

    if (!kit) {
      console.log(`[Worker] Invalid kit requested: ${currentOrder.kit}`)
      orderQueue.shift()
      continue
    }

    try {
      console.log(`[Worker] Executing Order: ${currentOrder.ign} x${currentOrder.qty} ${currentOrder.kit}`)

      const move = new Movements(playerBot, mcData)
      move.canDig = false
      playerBot.pathfinder.setMovements(move)
      await playerBot.pathfinder.goto(new goals.GoalBlock(kit.chest.x, kit.chest.y, kit.chest.z))

      const chestBlock = playerBot.findBlock({ matching: mcData.blocksByName.chest.id, maxDistance: 6 })
      if (!chestBlock) throw new Error('Chest block not found at coordinates')

      const chest = await playerBot.openContainer(chestBlock)
      let extracted = 0
      for (let i = 0; i < currentOrder.qty; i++) {
        const items = chest.slots.filter(s => s)
        if (!items.length) break
        await chest.withdraw(items[0].type, null, 1)
        extracted++
      }
      await chest.close()

      if (extracted === 0) throw new Error('Chest is empty')

      await sleep(1000)
      playerBot.chat(`/tpa ${currentOrder.ign}`)
      console.log('[Worker] Sent /tpa. Waiting for player...')

      await waitForPlayerToAcceptTPA(currentOrder.ign, 120)

      console.log(`[Worker] Order Successful for ${currentOrder.ign}!`)
      orderQueue.shift()

    } catch (err) {
      // THIS CATCH BLOCK HANDLES EVERY SINGLE FAILURE TYPE
      console.error(`[Worker] Order Exception: ${err.message}`)
      failOrder(currentOrder, err.message)
      orderQueue.shift()
    } finally {

      if (workerReady && playerBot && playerBot.entity) {
        console.log('[Worker] Resetting bot via /kill for next order...')
        playerBot.chat('/kill')
        await sleep(6000)
      }
    }
  }

  isProcessingQueue = false
}

console.log('Starting Minecraft Bot...')
startWorkerBot()