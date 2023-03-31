Finance Manager
===============

Finance Manager is a web-based application built using Django/Python. The application helps users manage their finances by providing features to handle transactions and visualizing the transaction data in charts. The current version is an alpha release and more features will be added in future updates.

Features
--------

*   User authentication: Users can login to the application.
*   Transaction handling: Users can add, edit, and delete transactions.
*   Chart visualization: Users can view their transaction data in various charts such as bar charts, pie charts, and line charts.

Requirements
------------

To run the Finance Manager application, you need the following installed on your system:

*   Python 3.11.2
*   Django 4.1.7

Installation
------------

1.  Clone the repository: `git clone git@github.com:himaldahal/finance-manager.git`
2.  Navigate into the project directory: `cd /finance-manager/`
3.  Install the required packages: `pip install -r requirements.txt`
4.  Create the database tables: `python manage.py migrate`
5.  Create the superuser: `python manage.py createsuperuser`
6.  Start the development server: `python manage.py runserver`
7.  Open the application in your web browser at [http://localhost:8000/](http://localhost:8000/)

Usage
-----

1.  Login to an existing account.
2.  Add transactions by clicking the "Add Transaction" button on the dashboard.
3.  View your transaction data in various charts by clicking the "Transaction" button on the dashboard.
4.  Edit or delete transactions by clicking the "Edit" or "Delete" button next to each transaction on the Transactions page.

Contribution
------------

If you want to contribute to the Finance Manager application, feel free to submit a pull request.

License
-------

The Finance Manager application is licensed under the [MIT License]

**Update:** A new version of the Finance Manager project (version 2) has been released and is available at [https://github.com/himaldahal/finance-manger/tree/V2](https://github.com/himaldahal/finance-manger/tree/V2).
