import requests, psycopg2, psycopg2.extras, os
import pandas as pd
from datetime import datetime, date, timedelta
from core.config import *
from scripts.send_mail import *
from discordwebhook import Discord
from scripts.functions import set_env
# from models import *
from sqlalchemy import select

env = set_env()

discord = Discord(url=env["DISCORD_WEBHOOK"])

def opening_range_strategy():
    #store the current date or a custom date for testing
    today = date.today()
    # today = datetime(2023, 11, 3).date()

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
        print(f"{today} is not a trading day (M - F)")
        return {"message": f"{today} is not a trading day (M - F)"}

    #get existing orders
    response = requests.get(f'{env["TRADIER_URL"]}/accounts/{env["ACCOUNT_ID"]}/orders',
        params={'includeTags': 'true'},
        headers={'Authorization': f'Bearer {env["TRADIER_KEY"]}', 'Accept': 'application/json'}
    )
    json_response = response.json()

    existing_order_symbols = []
    if json_response["orders"] != 'null':
        orders = json_response["orders"]["order"]
        order_status = ['open', 'filled', 'pending']

        #if there is only 1 existing order, the response will be a dictionary, if there are multiple orders it will be a list
        if type(orders) == dict:
            for order in orders["leg"]:

                # transform the create_date into a regular date format to match today
                create_date = order["create_date"]
                create_date = datetime.strptime(create_date, '%Y-%m-%dT%H:%M:%S.%fZ')
                create_date = create_date.date()

                #if the order was placed today, add the symbol to list
                if create_date == today and order["status"] in order_status:
                    existing_order_symbols.append(order["symbol"])
        else:
            # build list of existing option symbols
            for order in orders:

                # transform the create_date into a regular date format to match today
                create_date = order["create_date"]
                create_date = datetime.strptime(create_date, '%Y-%m-%dT%H:%M:%S.%fZ')
                create_date = create_date.date()

                #if the order was placed today and it is a bracket order with multiple legs, add the symbol to list
                if create_date == today and order["status"] in order_status and 'leg' in order.keys():
                    existing_order_symbols.append(order["leg"][0]["symbol"])

    # query database for opening range stategies that are applied to a stock

    connection = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cursor = connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute("""
            select stock.symbol as symbol, strategy.name as strategy
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
     
    resp: list = []
    data: dict = {}
    if rows:
        #loop through stock strategies for processing
        for row in rows:
            data: dict = {}
            #store symbol and strategy in vars
            symbol = row["symbol"]
            strategy = row["strategy"]
            print(f"processing {strategy} for {symbol}")
            data["strategy"] = f"processing {strategy} for {symbol}"

            #get the latest intraday minute data for stock
            df = get_historical_intraday(symbol, today, token=IEX_TOKEN)
            
            #check if we have data in the dataframe to process, if not exit the script
            if df.empty:
                print(f"no data yet for {today}, please try another date")
                data["message"] = f"no data yet for {today}, please try another date"
                
                quit()

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

            #get the current price of stock symbol
            stock = Stock(symbol, token=IEX_TOKEN)
            quote = stock.get_price()
            quote = quote[symbol].price

            #send request to get expiration dates and the strike prices
            response = requests.get(f'{env["TRADIER_URL"]}/markets/options/expirations',
                params={'symbol': symbol, 'includeAllRoots': 'true', 'strikes': 'true'},
                headers={'Authorization': f'Bearer {env["TRADIER_KEY"]}', 'Accept': 'application/json'}
            )

            json_response = response.json()

            #build list of expiratino dates
            expiration_dates = [row["date"] for row in json_response["expirations"]["expiration"]]

            #change expiration to string
            str_expiration = expiration.strftime("%Y-%m-%d")

            #check if expiration date exists in list of dates, if not set the expiration to the day before (Thursday)
            #this is to handle expiration fridays that are holidays or not trading days
            if str_expiration not in expiration_dates:
                expiration = expiration + timedelta(days = -1)
                str_expiration = expiration.strftime("%Y-%m-%d")

            #build list of strikes for the expiration day
            for row in json_response["expirations"]["expiration"]:
                if row["date"] == str_expiration:
                    strike_list = row["strikes"]["strike"]

            #calc the closest strike price to the current price for ATM option strike
            strike_price = min(strike_list, key=lambda x:abs(x-quote))

            #prep strike price to be added to the option symbol (00022000)
            strike_symbol = str(strike_price).zfill(7)
            strike_symbol = strike_symbol.replace('.', '')

            #init symbol vars to build option symbol
            expiration_symbol = expiration.strftime("%y%m%d")

            if strategy == "opening_range_breakout":
                signal = after_opening_range_bars[after_opening_range_bars['close'] > opening_range_high]
                order_type = 'C'
            elif strategy == "opening_range_breakdown":
                signal = after_opening_range_bars[after_opening_range_bars['close'] < opening_range_low]
                order_type = 'P'
            
            if not signal.empty:

                #build option symbol
                option_symbol = symbol + expiration_symbol + order_type + strike_symbol + '00'

                # check if order already exists and is there is a breakout trade signal
                if symbol not in existing_order_symbols:

                    try:
                        #send request to get available option chains
                        response = requests.get(f'{env["TRADIER_URL"]}/markets/options/chains',
                            params={'symbol': symbol, 'expiration': expiration},
                            headers={'Authorization': f'Bearer {env["TRADIER_KEY"]}', 'Accept': 'application/json'}
                        )
                        json_response = response.json()

                        #create list of available option chain symbols
                        option_chain_symbols = []
                        for row in json_response["options"]["option"]:
                            option_chain_symbols.append(row["symbol"])

                        #test if option_symbol is available from broker
                        if option_symbol in option_chain_symbols:

                            #get current price of option chain/contract
                            response = requests.get(f'{env["TRADIER_URL"]}/markets/quotes',
                                params={'symbols': option_symbol, 'greeks': 'false'},
                                headers={'Authorization': f'Bearer {env["TRADIER_KEY"]}', 'Accept': 'application/json'}
                            )
                            json_response = response.json()
                            option_limit_price = json_response["quotes"]["quote"]["last"]

                            #calc profit and loss of bracket trade
                            option_take_profit = round(option_limit_price * 1.1, 2)
                            option_stop_loss = round(option_limit_price * .8, 2)

                            #init option order payload
                            data={
                                    'class': 'otoco', 
                                    'duration': 'day', 
                                    'type[0]': 'limit', 
                                    'price[0]': option_limit_price, 
                                    'option_symbol[0]': option_symbol, 
                                    'side[0]': 'buy_to_open', 
                                    'quantity[0]': env["quantity"], 
                                    'type[1]': 'limit', 
                                    'price[1]': option_take_profit, 
                                    'option_symbol[1]': option_symbol, 
                                    'side[1]': 'sell_to_close', 
                                    'quantity[1]': env["quantity"], 
                                    'type[2]': 'stop', 
                                    'stop[2]': option_stop_loss, 
                                    'option_symbol[2]': option_symbol, 
                                    'side[2]': 'sell_to_close', 
                                    'quantity[2]': env["quantity"]
                                }
                            
                            #send request to create order
                            response = requests.post(f'{env["TRADIER_URL"]}/accounts/{env["ACCOUNT_ID"]}/orders',
                                data=data,
                                headers={'Authorization': f'Bearer {env["TRADIER_KEY"]}', 'Accept': 'application/json'}
                            )

                            json_response = response.json()
                            # print(json_response['errors'])
                            message = f"placing {strategy} order for {option_symbol} at {option_limit_price}, {symbol} closed above/below {opening_range_high}, at {signal.index[0]}"
                            print(message)
                            data["message"] = message

                            #send message to discord server
                            discord.post(content=message)

                            #send email with order details message
                            # notify(message)
                        else:
                            print(f"strike price {strike_price} not found for {symbol}")
                            data["Not_Found"] = f"strike price {strike_price} not found for {symbol}"
                    except Exception as e:
                        print(e)
                        # logging.warning(e)
                        data["Exception"] = f"{e}"
                        continue
                else:
                    print(f"order for {symbol} has already been executed today")
                    data["Exists"] = f"order for {symbol} already exists"
            else:
                print(f"no {strategy} entry signal for {symbol}")
                data["Entry"] = f"no {strategy} entry signal for {symbol}"
            resp.append(data)
            print("==========================================================")
    else:
        print("opening range strategy is not applied to any stocks")
        data["Not_Applied"] = "opening range strategy is not applied to any stocks"
        
    resp.append(data)
    current_time = datetime.now()

    for item in resp:
        for val in item.values():
            cursor.execute("insert into logs (date, time, task_name, log) VALUES (%s, %s, %s, %s)",(today.strftime("%Y-%m-%d"), current_time.strftime("%H:%M:%S"), "opening_range_strategy", val))
    connection.commit()    
    return resp