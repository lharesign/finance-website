import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # Get username to query stocks table and cash balance
    user_info = db.execute("SELECT * FROM users WHERE id = :user_id", user_id=session["user_id"])
    username = user_info[0]['username']
    cash = usd(user_info[0]['cash'])

    # Create variable to keep track of total value
    sum = user_info[0]['cash']

    # Get info on stocks owned by current user
    stocks = db.execute("SELECT * FROM stocks WHERE username = :username", username=username)

    # Loop through dictionary, adding current stock price and total value key pairs, and adding value to sum
    for row in stocks:

        sym_dict = lookup(row['symbol'])
        current_price = sym_dict['price']
        value = row['quantity'] * current_price
        row['current_price'] = usd(current_price)
        row['value'] = usd(value)
        sum += value

    # Converting sum to USD formatting
    sum = usd(sum)

    #Return the portfolio table
    return render_template("index.html", stocks=stocks, cash=cash, sum=sum)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    # If reached via POST method
    if request.method == "POST":

        symbol = (request.form.get("symbol").upper())
        sym_dict = lookup(symbol)

        # Check user provided an integer in shares, reject if not
        try:
            qty = int(request.form.get("shares"))
        except ValueError:
            return apology("must provide a valid quantity of shares to buy", 403)

        # Return error if no symbol provided
        if not symbol:
            return apology("must provide a symbol", 403)

        # Return error if no quantity provided
        if (qty <= 0):
            return apology("must provide a quantity of shares to buy", 403)

        if lookup(symbol) == None:
            return apology("please provide valid symbol", 403)

        # If all error checks passed, obtain share price and user cash balance
        share_price = sym_dict['price']
        cost = share_price * qty
        balance = db.execute("SELECT cash FROM users WHERE id = :user_id", user_id=session["user_id"])
        balance = balance[0]['cash']

        # Check if user can afford purchase
        if (balance - cost) < 0:
            return apology("insufficient funds")

        # If user can afford, update stocks.db
        else:
            # Update balance to reflect cash minus cost
            balance = balance - cost

            # Update the users table with latest balance
            db.execute("UPDATE users SET cash = :balance WHERE id = :user_id", balance=balance, user_id=session["user_id"])

            # Fetch username of user
            username = db.execute("SELECT username FROM users WHERE id = :user_id", user_id=session["user_id"])
            username = username[0]['username']

            # Insert into stocks the username that bought the stock and the stock info
            # If user doesn't own any shares in company, add to stocks.db
            if not db.execute("SELECT symbol FROM stocks WHERE username = :username AND symbol = :symbol", username=username, symbol=symbol):
                db.execute("INSERT INTO stocks (username, symbol, stock_name, price, quantity) VALUES (:username, :symbol, :stock_name, :price, :quantity)",
                        username=username, symbol=symbol, stock_name=sym_dict["name"], price=share_price, quantity=qty)

            # If user already owns shares in that company, update quantity in stocks.db
            else:
                quantity_owned = db.execute("SELECT quantity FROM stocks WHERE username = :username AND symbol = :symbol", username=username, symbol=symbol)
                quantity_owned = int(quantity_owned[0]['quantity']) + qty
                db.execute("UPDATE stocks SET quantity = :quantity WHERE username = :username AND symbol = :symbol", quantity=quantity_owned, username=username, symbol=symbol)

            # Insert transaction into history.db
            db.execute("INSERT INTO history (username, symbol, stock_name, price, quantity) VALUES (:username, :symbol, :stock_name, :price, :quantity)",
                    username=username, symbol=symbol, stock_name=sym_dict['name'], price=share_price, quantity=qty)

            flash("Bought!")
            return redirect("/")

    # If reached vie GET method
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    # Get username to query history table
    user_info = db.execute("SELECT * FROM users WHERE id = :user_id", user_id=session["user_id"])
    username = user_info[0]['username']

    # Get info on transactions completed by current user
    history = db.execute("SELECT * FROM history WHERE username = :username", username=username)

    #Return the history table
    return render_template("history.html", history=history)

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        flash("Login Successful!")
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    # If submitted via POST, look up symbol info
    if request.method == "POST":

        # If no symbol provided, return error
        if not request.form.get("symbol"):
            return apology("must provide a symbol", 403)

        # If symbol provided, use lookup()
        else:
            symbol = request.form.get("symbol")
            symbol = lookup(symbol)

            # Check if symbol lookup returns any data
            if symbol != None:

                # If data returned, display it
                return render_template("quoted.html", symbol=symbol)

            # If no data returned, ask user to provide a valaid symbol
            else:
                return apology("provide a valid symbol", 403)

    # If submitted via GET, return quote webpage
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

     # Forget any user_id
    session.clear()

    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Ensure confirmation password was submitted
        elif not request.form.get("confirmation"):
            return apology("must confirm password", 403)

        # Ensure password and confirmation password match
        elif not (request.form.get("password") == request.form.get("confirmation")):
            return apology("passwords must match", 403)

        # Check DB for username provided
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # If username returns anything, then it is already taken
        if len(rows) == 1:
            return apology("username already taken", 403)

        username = request.form.get("username")
        hash = generate_password_hash(request.form.get("password"))

        db.execute("INSERT INTO users (username, hash) VALUES (:username, :hash)", username=username, hash=hash)
        flash("Registered Successfully!")
        return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    # Finding username so it can be used in get and post methods
    username = db.execute("SELECT username FROM users WHERE id = :user_id", user_id=session["user_id"])
    username = username[0]['username']

    # If reached via POST, sell shares if possible
    if request.method == "POST":
        shares = int(request.form.get("shares"))
        symbol = request.form.get("symbol")

        # If no quantity provided, or quantity is below zero, return error
        if not shares or (shares <= 0):
            return apology("please input valid number of shares to sell", 403)

        # If no symbol selected, return error
        elif symbol == "Symbol":
            return apology("please select symbol to sell", 403)

        else:

            # Query DB to discover how many shares of particular symbol user owns
            stocks = db.execute("SELECT quantity FROM stocks WHERE username = :username AND symbol = :symbol GROUP BY symbol", username=username, symbol=symbol)
            current_shares = int(stocks[0]['quantity'])

            # If user is trying to sell more shares than they own, return error
            if current_shares < shares:
                return apology("you're trying to sell more shares than you own", 403)

            else:

                # Calculate price of one share and value of the qty being sold
                sym_dict = lookup(symbol)
                price = sym_dict['price']
                value = price * shares

                # Increase users cash balance by value of sold shares
                cash = db.execute("SELECT cash FROM users WHERE username = :username", username=username)
                cash = int(cash[0]['cash'])
                cash += value
                db.execute("UPDATE users SET cash = :cash WHERE username = :username", cash=cash, username=username)

                # Update users portfolio so sold shares are removed
                # If the numberof shares sold equals the number of shares owned, remove from DB completely
                if current_shares == shares:
                    db.execute("DELETE FROM stocks WHERE username = :username AND symbol = :symbol", username=username, symbol=symbol)


                # Otherwise, update qty to reflect how many were sold
                else:
                    current_shares -= shares
                    db.execute("UPDATE stocks SET quantity = :current_shares WHERE username= :username AND symbol = :symbol", current_shares=current_shares, username=username, symbol=symbol)

                # Insert transaction into history.db
                db.execute("INSERT INTO history (username, symbol, stock_name, price, quantity) VALUES (:username, :symbol, :stock_name, :price, :quantity)",
                            username=username, symbol=symbol, stock_name=sym_dict['name'], price=price, quantity=(0-shares))

                flash("Sold!")
                return redirect("/")

    # If reached via GET, display webpage
    else:
        stocks = db.execute("SELECT symbol FROM stocks WHERE username = :username GROUP BY symbol", username=username)
        return render_template("sell.html", stocks=stocks)

@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    """Change password"""

    if request.method == "POST":

        # Query database for username
        user_info = db.execute("SELECT * FROM users WHERE id = :user_id", user_id=session["user_id"])

        # Ensure password was submitted
        if not request.form.get("old_password"):
            return apology("must provide password", 403)

        # Ensure new password submitted
        elif not request.form.get("new_password"):
            return apology("must provide new password", 403)

        # Ensure confirmation password was submitted
        elif not request.form.get("new_confirmation"):
            return apology("must confirm new password", 403)

        # Ensure password and confirmation password match
        elif not (request.form.get("new_password") == request.form.get("new_confirmation")):
            return apology("new passwords must match", 403)

        # Ensure hash value of original password provided is correct
        elif not (check_password_hash(user_info[0]["hash"], request.form.get("old_password"))):
            return apology("current password is invalid", 403)

        # Generate new hash and update usernames hash value in users table
        else:
            new_hash = generate_password_hash(request.form.get("new_password"))
            username = user_info[0]['username']
            db.execute("UPDATE users SET hash = :hash WHERE username = :username", hash=new_hash, username=username)

            flash("Password Changed!")
            return redirect("/")

    else:
        return render_template("account.html")

def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
