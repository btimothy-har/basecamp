# Build context is the repo root (parent of deploy/): mkdocs.yml and docs/
# live there and are shipped alongside deploy/ to the remote deploy root.
FROM squidfunk/mkdocs-material AS build
WORKDIR /docs
COPY mkdocs.yml ./
COPY docs/ ./docs/
RUN mkdocs build --strict

FROM nginx:alpine
COPY --from=build /docs/site/ /usr/share/nginx/html/
EXPOSE 80
