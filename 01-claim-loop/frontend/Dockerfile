# Development image. A production build is `npm run build` plus a static host --
# a bucket or Firebase Hosting, not a container. Serving static files from
# compute is paying for a CPU to read a file.
FROM node:22-slim

WORKDIR /app

# Dependencies in their own layer, so editing src/ does not reinstall them.
COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]
