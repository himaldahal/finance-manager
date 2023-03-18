Finance Manager

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

*   Python 3.x
*   Django 3.x
*   matplotlib

Installation
------------

1.  Clone the repository:

git clone https://github.com/<username>/<repository>.git

3.  Navigate into the project directory:

cd /finance-manger/

5.  Install the required packages:

pip install -r requirements.txt

7.  Create the database tables:

python manage.py migrate

9.  Start the development server:

python manage.py runserver

11.  Open the application in your web browser at http://localhost:8000/

Usage
-----

1.  Create an account or login to an existing account.
2.  Add transactions by clicking the "Add Transaction" button on the dashboard.
3.  View your transaction data in various charts by clicking the "Charts" button on the dashboard.
4.  Edit or delete transactions by clicking the "Edit" or "Delete" button next to each transaction on the Transactions page.

Contribution
------------

If you want to contribute to the Finance Manager application, feel free to submit a pull request. Please make sure to follow the [contributing guidelines](CONTRIBUTING.md).

License
-------

The Finance Manager application is licensed under the [MIT License](LICENSE).
