# Реальные семплы websocket-сообщений (Kraken v2, Coinbase Exchange)

Дата захвата: 2026-10-03 (UTC)
Инструмент: `websocket-client==1.9.0`, Python 3.13.5
Сеть: живое подключение успешно, TLS без прокси-проблем.

Все семплы ниже — реальные сообщения, полученные от провайдеров (значения цен/времени
меняются, схема полей стабильна).

---

## Kraken WebSocket v2

- Endpoint: `wss://ws.kraken.com/v2`
- Subscribe: `{"method":"subscribe","params":{"channel":"ticker","symbol":["BTC/USD","ALGO/USD"]}}`

### 1. Kraken status (приходит сразу после connect)

```json
{"channel":"status","type":"update","data":[{"version":"2.0.10","system":"online","api_version":"v2","connection_id":3364750901719990046,"upcoming_maintenance":[{"affected_services":["spot_trading","spot_fix","spot_ws"],"cancel_before_utc":"2026-10-05T08:55:00.000000Z","event_id":33,"expected_end_utc":"2026-10-05T10:00:00.000000Z","expected_start_utc":"2026-10-05T09:00:00.000000Z","order_submission":"allowed","phase":"announced","recommended_action":"continue","source_url":"https://stspg.io/1w11k0cnnv3j","time_to_start_s":129689,"title":"Order Entry System Maintenance"}],"emergency":[]}]}
```

### 2. Kraken subscribe-ack

```json
{"method":"subscribe","result":{"channel":"ticker","event_trigger":"trades","snapshot":true,"symbol":"BTC/USD"},"success":true,"time_in":"2026-10-03T20:58:30.560234Z","time_out":"2026-10-03T20:58:30.560271Z"}
```

### 3. Kraken ticker snapshot

```json
{"channel":"ticker","type":"snapshot","data":[{"symbol":"ALGO/USD","bid":0.13099,"bid_qty":329.06250000,"ask":0.13108,"ask_qty":1771.75027615,"last":0.13110,"volume":9095630.20903971,"vwap":0.12882,"low":0.12437,"high":0.13306,"change":0.00654,"change_pct":5.25,"trades":4606,"timestamp":"2026-10-03T20:58:33.794283Z"}]}
```

Примечание: `type` может быть `snapshot` (первое сообщение по символу) или `update`
(последующие). Данные лежат в массиве `data[]`, а не в корне сообщения.

---

## Coinbase Exchange

- Endpoint: `wss://ws-feed.exchange.coinbase.com`
- Subscribe: `{"type":"subscribe","product_ids":["BTC-USD"],"channels":["ticker_batch"]}`

### 4. Coinbase subscriptions-ack

```json
{"type":"subscriptions","channels":[{"name":"ticker_1000","product_ids":["BTC-USD"],"account_ids":null}]}
```

### 5. Coinbase ticker

```json
{"type":"ticker","sequence":137212619516,"product_id":"BTC-USD","price":"84737.58","open_24h":"84430.55","volume_24h":"1836.96781750","low_24h":"84400","high_24h":"85021.57","volume_30d":"175984.53012145","best_bid":"84737.58","best_bid_size":"0.19921154","best_ask":"84737.59","best_ask_size":"0.05223077","side":"sell","time":"2026-10-03T20:58:31.127510Z","trade_id":1102042811,"last_size":"0.00000025"}
```

---

## Расхождения с ожиданиями Task 3

1. **Kraken subscribe-ack не содержит `type: snapshot`/`update`.**
   Подтверждающее сообщение подписки имеет поля `method`, `result`, `success`,
   `time_in`, `time_out`. Поля `symbol`, `last`, `change` находятся только в отдельном
   сообщении канала `ticker` (`channel":"ticker"`, `type":"snapshot"|"update"`, `data[]`).
   Парсер должен различать ack (`method`/`success`) и данные (`channel":"ticker"`).

2. **Kraken первое сообщение — `channel:"status"`, не ticker.**
   Перед данными о ценах прилетает статус-сообщение. Его нужно игнорировать.

3. **Coinbase ack называет канал `ticker_1000`, а не `ticker_batch`.**
   В запросе используется `ticker_batch`, но в подтверждении подписки имя канала —
   `ticker_1000`. Сообщения данных по-прежнему имеют `type: "ticker"`.

4. **Coinbase числовые поля — строки.**
   `price`, `open_24h`, `volume_24h`, `best_bid` и т.д. приходят как строки, их нужно
   приводить к float при парсинге. Совпадает с ожиданием (`price`, `open_24h` есть).

5. **Coinbase не отдаёт `change`/`change_pct` напрямую.**
   Для процента изменения нужно вычислять из `price` и `open_24h`. В Kraken есть готовые
   поля `change` и `change_pct`.
