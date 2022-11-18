import json
import psycopg2, psycopg2.extras, requests
import pandas as pd
from datetime import datetime, date, timedelta
from iexfinance.stocks import Stock, get_historical_intraday, get_historical_data
from config.config import *
from send_raw_mail import *

#store the current date or a custom date for testing
today = date.today()
# today = datetime(2022, 11, 16)

#only run the script if the date above is a weekday
if today.weekday() == 0:
    expiration = today + timedelta(days = 4)
elif today.weekday() == 1:
    expiration = today + timedelta(days = 3)
elif today.weekday() == 2:
    expiration = today + timedelta(days = 2)
elif today.weekday() == 3:
    expiration = today + timedelta(days = 1)
elif today.weekday() == 4:
    expiration = today + timedelta(days = 7)
else:
    print("it is not a trading day (M - F)")
    quit()

#get existing orders
response = requests.get('https://sandbox.tradier.com/v1/accounts/VA41833079/orders',
    params={'includeTags': 'true'},
    headers={'Authorization': f'Bearer {TRADIER_SANDBOX_KEY}', 'Accept': 'application/json'}
)
json_response = response.json()

existing_order_symbols = []

if json_response["orders"] != 'null':
    orders = json_response["orders"]["order"]

    # build list of existing option symbols
    for order in orders:

        # transform th create_date into a regular date format to match today
        create_date = order["create_date"]
        create_date = datetime.strptime(create_date, '%Y-%m-%dT%H:%M:%S.%fZ')
        create_date = create_date.date()

        #if the order was placed today, add the symbol to variable
        if create_date == today:
            existing_order_symbols.append(order["leg"][0]["option_symbol"])

# print(existing_order_symbols)

# query database for opening range stategies that are applied to a stock
connection = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
cursor = connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
cursor.execute("""
        select stock_strategy.stock_id, stock_strategy.strategy_id, stock.symbol as symbol, strategy.name as strategy
        from stock_strategy
        join stock on stock_strategy.stock_id = stock.id
        join strategy on stock_strategy.strategy_id = strategy.id
        where strategy.name like 'opening_range%'
        order by stock_id ASC
    """)
rows = cursor.fetchall()

#store start and end of 15 minute opening range
start_minute_bar = f"{today} 09:30:00"
end_minute_bar = f"{today} 09:45:00"

#loop through stock strategies for processing
for row in rows:
    #store symbol and strategy in vars
    symbol = row["symbol"]
    strategy = row["strategy"]
    print(f"processing {strategy} for {symbol}")

    #get the latest intraday minute data for stock
    df = get_historical_intraday(symbol, today, token=IEX_TOKEN)

    #store minute bars for first 15 minutes
    opening_range_mask = (df.index >= start_minute_bar) & (df.index <= end_minute_bar)
    opening_range_bars = df[opening_range_mask]

    #store minute bars for after first 15 minutes
    after_opening_range_mask = (df.index > end_minute_bar)
    after_opening_range_bars = df[after_opening_range_mask]

    #calc the 15 minute opening range
    opening_range_low = opening_range_bars["low"].min()
    opening_range_high = opening_range_bars["high"].max()
    opening_range = round(opening_range_high - opening_range_low, 2)

    # print(f"Opening Range Low: {opening_range_low}")
    # print(f"Opening Range High: {opening_range_high}")
    # print(f"Opening Range: {opening_range}")

    #get the current price of stock symbol
    stock = Stock(f'{symbol}', token=IEX_TOKEN)
    quote = stock.get_price()
    quote = quote[f"{symbol}"].price

    #get list of strike prices
    response = requests.get('https://sandbox.tradier.com/v1/markets/options/strikes',
        params={'symbol': symbol, 'expiration': expiration},
        headers={'Authorization': f'Bearer {TRADIER_SANDBOX_KEY}', 'Accept': 'application/json'}
    )
    json_response = response.json()
    strike_list = json_response["strikes"]["strike"]

    #calc the closest strike price to the current price for ATM option strike
    strike_price = min(strike_list, key=lambda x:abs(x-quote))

    #prep strike price to be added to the option symbol (00022000)
    strike_symbol = str(strike_price).zfill(7)
    strike_symbol = strike_symbol.replace('.', '')

    #init symbol vars to build option symbol
    expiration_symbol = expiration.strftime("%y%m%d")
    call = 'C'
    put = 'P'

    #get minute bars where the close is greater/less than the opening range
    breakout_signal = after_opening_range_bars[after_opening_range_bars['close'] > opening_range_high]
    breakdown_signal = after_opening_range_bars[after_opening_range_bars['close'] < opening_range_low]

    if strategy == "opening_range_breakout":

        #if the breakout symbol is not empty
        if not breakout_signal.empty:

            #build option symbol
            option_symbol = symbol + expiration_symbol + call + strike_symbol + '00'

            # check if order already exists and is there is a breakout trade signal
            if option_symbol not in existing_order_symbols:

            # print(option_symbol)

                try:
                    #send request to get available option chains
                    response = requests.get('https://sandbox.tradier.com/v1/markets/options/chains',
                        params={'symbol': symbol, 'expiration': expiration},
                        headers={'Authorization': f'Bearer {TRADIER_SANDBOX_KEY}', 'Accept': 'application/json'}
                    )
                    json_response = response.json()

                    #create list of available option chain symbols
                    option_chain_symbols = []
                    for row in json_response["options"]["option"]:
                        option_chain_symbols.append(row["symbol"])

                    #test if option_symbol is available from broker
                    if option_symbol in option_chain_symbols:

                        #get current price of option chain/contract
                        response = requests.get('https://sandbox.tradier.com/v1/markets/quotes',
                            params={'symbols': option_symbol, 'greeks': 'false'},
                            headers={'Authorization': f'Bearer {TRADIER_SANDBOX_KEY}', 'Accept': 'application/json'}
                        )
                        json_response = response.json()
                        option_limit_price = json_response["quotes"]["quote"]["last"]

                        #calc profit and loss of bracket trade
                        option_take_profit = round(option_limit_price * 1.1, 2)
                        option_stop_loss = round(option_limit_price * .8, 2)

                        #VARS AND PAYLOAD FOR REGULAR STOCKS (NOT OPTIONS)
                        # limit_price = int(breakout_signal.iloc[0]['close'])
                        # take_profit = limit_price + opening_range
                        # stop_loss = limit_price - opening_range
                        # data={
                        #             'class': 'otoco', 
                        #             'duration': 'day', 
                        #             'type[0]': 'limit', 
                        #             'price[0]': f'{limit_price}', 
                        #             'symbol[0]': f'{symbol}', 
                        #             'side[0]': 'buy', 
                        #             'quantity[0]': '10', 
                        #             'type[1]': 'limit', 
                        #             'price[1]': f'{limit_price + opening_range}', 
                        #             'symbol[1]': f'{symbol}', 
                        #             'side[1]': 'sell', 
                        #             'quantity[1]': '10', 
                        #             'type[2]': 'stop', 
                        #             'stop[2]': f'{limit_price - opening_range}', 
                        #             'symbol[2]': f'{symbol}', 
                        #             'side[2]': 'sell', 
                        #             'quantity[2]': '10'
                        #         }

                        #init option order payload
                        data={
                                'class': 'otoco', 
                                'duration': 'day', 
                                'type[0]': 'limit', 
                                'price[0]': option_limit_price, 
                                'option_symbol[0]': option_symbol, 
                                'side[0]': 'buy_to_open', 
                                'quantity[0]': '10', 
                                'type[1]': 'limit', 
                                'price[1]': option_take_profit, 
                                'option_symbol[1]': option_symbol, 
                                'side[1]': 'sell_to_close', 
                                'quantity[1]': '10', 
                                'type[2]': 'stop', 
                                'stop[2]': option_stop_loss, 
                                'option_symbol[2]': option_symbol, 
                                'side[2]': 'sell_to_close', 
                                'quantity[2]': '10'
                            }
                      
                        #send request to create order
                        response = requests.post('https://sandbox.tradier.com/v1/accounts/VA41833079/orders',
                            data=data,
                            headers={'Authorization': f'Bearer {TRADIER_SANDBOX_KEY}', 'Accept': 'application/json'}
                        )

                        json_response = response.json()
                        # print(json_response['errors'])
                        message = f"placing {strategy} order for {option_symbol} at {option_limit_price}, {symbol} closed above {opening_range_high}, at {breakout_signal.index[0]}"
                        print(message)

                        #send email with order details message
                        notify(message)
                    else:
                        print(f"{option_symbol} not found in option chain list")
                        print(f"strike price {strike_price} not found for {symbol}")
                except Exception as e:
                    print(e)
                    print("==========================================================")
                    continue
            else:
                print(f"order for {option_symbol} already exists")
        else:
            print(f"no {strategy} entry signal for {symbol}")

    elif strategy == "opening_range_breakdown":
        if not breakdown_signal.empty:

            option_symbol = symbol + expiration_symbol + put + strike_symbol + '00'

            if option_symbol not in existing_order_symbols:

                try:
                    response = requests.get('https://sandbox.tradier.com/v1/markets/options/chains',
                        params={'symbol': symbol, 'expiration': expiration},
                        headers={'Authorization': f'Bearer {TRADIER_SANDBOX_KEY} ', 'Accept': 'application/json'}
                    )
                    json_response = response.json()
    
                    option_chain_symbols = []
                    for row in json_response["options"]["option"]:
                        option_chain_symbols.append(row["symbol"])
                                
                    if option_symbol in option_chain_symbols:
                        response = requests.get('https://sandbox.tradier.com/v1/markets/quotes',
                            params={'symbols': option_symbol, 'greeks': 'false'},
                            headers={'Authorization': f'Bearer {TRADIER_SANDBOX_KEY}', 'Accept': 'application/json'}
                        )
                        json_response = response.json()

                        option_limit_price = json_response["quotes"]["quote"]["last"]
                        option_take_profit = round(option_limit_price * 1.1, 2)
                        option_stop_loss = round(option_limit_price * .8, 2)

                        #VARS AND PAYLOAD FOR REGULAR STOCKS (NOT OPTIONS)
                        # limit_price = int(breakdown_signal.iloc[0]['close'])
                        # take_profit = limit_price + opening_range
                        # stop_loss = limit_price - opening_range
                        # data = {
                        #             'class': 'otoco', 
                        #             'duration': 'day', 
                        #             'type[0]': 'limit', 
                        #             'price[0]': f'{limit_price}', 
                        #             'symbol[0]': f'{symbol}', 
                        #             'side[0]': 'buy', 
                        #             'quantity[0]': '10', 
                        #             'type[1]': 'limit', 
                        #             'price[1]': f'{limit_price - opening_range}', 
                        #             'symbol[1]': f'{symbol}', 
                        #             'side[1]': 'sell', 
                        #             'quantity[1]': '10', 
                        #             'type[2]': 'stop', 
                        #             'stop[2]': f'{limit_price + opening_range}', 
                        #             'symbol[2]': f'{symbol}', 
                        #             'side[2]': 'sell', 
                        #             'quantity[2]': '10'
                        #         }
                        data = {
                                    'class': 'otoco', 
                                    'duration': 'day', 
                                    'type[0]': 'limit', 
                                    'price[0]': option_limit_price, 
                                    'option_symbol[0]': option_symbol, 
                                    'side[0]': 'buy_to_open', 
                                    'quantity[0]': '10', 
                                    'type[1]': 'limit', 
                                    'price[1]': option_take_profit, 
                                    'option_symbol[1]': option_symbol, 
                                    'side[1]': 'sell_to_close', 
                                    'quantity[1]': '10', 
                                    'type[2]': 'stop', 
                                    'stop[2]': option_stop_loss, 
                                    'option_symbol[2]': option_symbol, 
                                    'side[2]': 'sell_to_close', 
                                    'quantity[2]': '10'
                                }
                        response = requests.post('https://sandbox.tradier.com/v1/accounts/VA41833079/orders',
                            data=data,
                            headers={'Authorization': f'Bearer {TRADIER_SANDBOX_KEY}', 'Accept': 'application/json'}
                        )
                        json_response = response.json()
                        print(json_response['errors'])
                        message=f"placing {strategy} order for {option_symbol} at {option_limit_price}, {symbol} closed below {opening_range_low}, at {breakdown_signal.index[0]}"
                        print(message)
                        notify(message)
                    else:
                        print(f"{option_symbol} not found in option chain list")
                        print(f"strike price {strike_price} not found for {symbol}")
                except Exception as e:
                    print(e)
                    print("==========================================================")
                    continue
            else:
                print(f"order for {option_symbol} already exists")
        else:
            print(f"no {strategy} entry signal for {symbol}")

    print("==========================================================")