# Telegram Group Assistant Bot

This is a starter Telegram group bot designed to run as a Render free Web Service.

## Environment variables
- BOT_TOKEN = your BotFather token (keep secret)
- ADMIN_CONTACT = your Telegram admin username, e.g. @example
- CITY = prayer-time city (default Dhaka)
- COUNTRY = country (default Bangladesh)
- TIMEZONE = Asia/Dhaka

## Deploy
1. Put these files in a GitHub repository.
2. On Render create a new Web Service from the repository.
3. Select the Free plan.
4. Add the environment variables above.
5. Deploy.
6. Copy the Render URL, for example:
   https://YOUR-SERVICE.onrender.com
7. Set Telegram webhook by opening this URL in a browser:
   https://api.telegram.org/botYOUR_TOKEN/setWebhook?url=https://YOUR-SERVICE.onrender.com/telegram/webhook

Do NOT publish YOUR_TOKEN anywhere.

## Important
Render free services can spin down after 15 minutes without inbound traffic, so this free setup is suitable for testing/hobby use but is not a guarantee of uninterrupted 24/7 availability. For true always-on operation, a paid/always-on host is needed.

The song/drama sections intentionally use placeholders: add your own lawful/authorized links or a database later.
