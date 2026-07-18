FROM composer:2.8@sha256:5248900ab8b5f7f880c2d62180e40960cd87f60149ec9a1abfd62ac72a02577c AS composer_tool

FROM php:8.2-fpm-bookworm@sha256:a335d57be82b3a392fe5c6287571de29d0b11c491826c783318ccb785dc0f262 AS php_extensions

SHELL ["/bin/sh", "-euxc"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        $PHPIZE_DEPS \
        ca-certificates \
        libcurl4 \
        libcurl4-openssl-dev \
        libfreetype6 \
        libfreetype6-dev \
        libicu72 \
        libicu-dev \
        libjpeg62-turbo \
        libjpeg62-turbo-dev \
        libonig5 \
        libonig-dev \
        libpng16-16 \
        libpng-dev \
        libxml2 \
        libxml2-dev \
        libzip4 \
        libzip-dev \
        unzip \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && extensions="" \
    && for extension in bcmath dom gd intl mbstring opcache pdo_mysql posix simplexml xml xmlreader xmlwriter zip; do \
        if ! php -r "exit(extension_loaded('$extension') ? 0 : 1);"; then \
            extensions="$extensions $extension"; \
        fi; \
    done \
    && if [ -n "$extensions" ]; then docker-php-ext-install -j"$(nproc)" $extensions; fi \
    && apt-get purge -y --auto-remove \
        $PHPIZE_DEPS \
        libcurl4-openssl-dev \
        libfreetype6-dev \
        libicu-dev \
        libjpeg62-turbo-dev \
        libonig-dev \
        libpng-dev \
        libxml2-dev \
        libzip-dev \
        unzip \
    && rm -rf /var/lib/apt/lists/*

FROM php_extensions AS build

ARG MIAOMU_RELEASE_SHA

COPY --from=composer_tool /usr/bin/composer /usr/local/bin/composer

WORKDIR /var/www/html
COPY . .

RUN [ "${#MIAOMU_RELEASE_SHA}" -eq 40 ] \
    && case "$MIAOMU_RELEASE_SHA" in \
        *[!0-9a-f]*) echo "invalid MIAOMU_RELEASE_SHA" >&2; exit 64 ;; \
        *) : ;; \
    esac \
    && composer validate --strict --no-check-publish --no-check-all \
    && composer install \
        --no-dev \
        --prefer-dist \
        --no-interaction \
        --no-progress \
        --optimize-autoloader \
        --classmap-authoritative \
    && composer check-platform-reqs --no-dev \
    && install -D -m 0444 tests/ops/environment_check.php /opt/miaomu/environment_check.php \
    && php /opt/miaomu/environment_check.php --build \
    && php deploy/docker/app/extract-schema.php config/shopxo.sql /opt/miaomu/shopxo-schema.sql deploy/shopxo-schema-baseline-manifest.json \
    && printf '%s\n' "$MIAOMU_RELEASE_SHA" > /opt/miaomu/release-sha \
    && chmod 0444 /opt/miaomu/release-sha \
    && rm -rf \
        .agents \
        .codex \
        .git \
        .github \
        .harness \
        deploy \
        docs \
        scripts \
        tests \
        rsakeys \
        config/shopxo.sql

FROM php_extensions AS runtime

ARG MIAOMU_RELEASE_SHA

LABEL org.opencontainers.image.title="miaomu-shopxo" \
      org.opencontainers.image.revision="${MIAOMU_RELEASE_SHA}" \
      com.centurylinklabs.watchtower.enable="false"

WORKDIR /var/www/html

COPY --from=build --chown=0:0 /var/www/html /var/www/html
COPY --from=build --chown=0:0 /opt/miaomu/environment_check.php /usr/local/lib/miaomu/environment_check.php
COPY --from=build --chown=0:0 /opt/miaomu/shopxo-schema.sql /usr/local/share/miaomu/shopxo-schema.sql
COPY --from=build --chown=0:0 /opt/miaomu/release-sha /usr/local/share/miaomu/release-sha
COPY --chown=0:0 deploy/docker/app/php.ini /usr/local/etc/php/php.ini
COPY --chown=0:0 deploy/docker/app/www.conf /usr/local/etc/php-fpm.d/zz-miaomu.conf
COPY --chown=0:0 deploy/docker/app/fpm-entry-guard.php /usr/local/lib/miaomu/fpm-entry-guard.php
COPY --chown=0:0 deploy/docker/app/shopxo-schema-bootstrap.php /usr/local/lib/miaomu/shopxo-schema-bootstrap.php
COPY --chown=0:0 deploy/docker/app/nursery-bootstrap.php /usr/local/lib/miaomu/nursery-bootstrap.php
COPY --chown=0:0 deploy/docker/app/docker-entrypoint.sh /usr/local/bin/miaomu-entrypoint
COPY --chown=0:0 deploy/docker/app/runtime-sanitize.sh /usr/local/bin/miaomu-runtime-sanitize

RUN rm -f \
        /usr/local/etc/php-fpm.d/www.conf \
        /usr/local/etc/php-fpm.d/www.conf.default \
        /usr/local/etc/php-fpm.d/zz-docker.conf \
    && groupadd --gid 10001 miaomu \
    && useradd \
        --uid 10001 \
        --gid 10001 \
        --home-dir /nonexistent \
        --no-create-home \
        --shell /usr/sbin/nologin \
        miaomu \
    && install -o 0 -g 0 -m 0444 /dev/null /var/www/html/app/event.php \
    && install -d -o 10001 -g 10001 -m 0770 \
        /run/miaomu-fpm \
        /var/www/html/runtime \
        /var/www/html/public/static/upload \
        /var/www/html/public/download \
    && find /var/www/html -xdev -type d -exec chmod 0555 {} + \
    && find /var/www/html -xdev -type f -exec chmod 0444 {} + \
    && chown -R 10001:10001 \
        /var/www/html/runtime \
        /var/www/html/public/static/upload \
        /var/www/html/public/download \
    && find \
        /var/www/html/runtime \
        /var/www/html/public/static/upload \
        /var/www/html/public/download \
        -type d -exec chmod 0770 {} + \
    && find \
        /var/www/html/runtime \
        /var/www/html/public/static/upload \
        /var/www/html/public/download \
        -type f -exec chmod 0660 {} + \
    && chmod 0555 \
        /usr/local/bin/miaomu-entrypoint \
        /usr/local/bin/miaomu-runtime-sanitize \
    && chmod 0444 \
        /usr/local/etc/php/php.ini \
        /usr/local/etc/php-fpm.d/zz-miaomu.conf \
        /usr/local/lib/miaomu/environment_check.php \
        /usr/local/lib/miaomu/fpm-entry-guard.php \
        /usr/local/lib/miaomu/shopxo-schema-bootstrap.php \
        /usr/local/lib/miaomu/nursery-bootstrap.php \
        /usr/local/share/miaomu/shopxo-schema.sql \
        /usr/local/share/miaomu/release-sha

USER 10001:10001

ENTRYPOINT ["/usr/local/bin/miaomu-entrypoint"]
CMD ["php-fpm", "--nodaemonize", "--fpm-config", "/usr/local/etc/php-fpm.conf"]
