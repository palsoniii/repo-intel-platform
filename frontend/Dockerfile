FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install

COPY . .

EXPOSE 5180

# Dev server, not a production build -- matches the project's existing `npm run dev`
# workflow. --host so it's reachable from outside the container; the frontend talks
# to the backend via http://localhost:8000 from the BROWSER (not container-to-container),
# so no API_BASE_URL rewiring is needed as long as the backend's port is published too.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
