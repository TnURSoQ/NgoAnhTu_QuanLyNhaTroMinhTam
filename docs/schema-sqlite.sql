-- SQLite development schema, exported 2026-11-19.
-- Source of application schema: Django migrations. No application data included.

-- table: accounts_tenant
CREATE TABLE "accounts_tenant" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "full_name" varchar(100) NOT NULL, "id_card_number" varchar(20) NOT NULL UNIQUE, "phone" varchar(20) NOT NULL, "email" varchar(254) NULL, "date_of_birth" date NULL, "hometown" varchar(255) NULL, "user_id" bigint NULL UNIQUE REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "note" text NOT NULL, "occupation" varchar(100) NOT NULL);

-- table: accounts_user
CREATE TABLE "accounts_user" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "password" varchar(128) NOT NULL, "last_login" datetime NULL, "is_superuser" bool NOT NULL, "username" varchar(150) NOT NULL UNIQUE, "first_name" varchar(150) NOT NULL, "last_name" varchar(150) NOT NULL, "email" varchar(254) NOT NULL, "is_staff" bool NOT NULL, "is_active" bool NOT NULL, "date_joined" datetime NOT NULL, "role" varchar(20) NOT NULL);

-- table: accounts_user_groups
CREATE TABLE "accounts_user_groups" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "group_id" integer NOT NULL REFERENCES "auth_group" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: accounts_user_user_permissions
CREATE TABLE "accounts_user_user_permissions" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "permission_id" integer NOT NULL REFERENCES "auth_permission" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: auth_group
CREATE TABLE "auth_group" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(150) NOT NULL UNIQUE);

-- table: auth_group_permissions
CREATE TABLE "auth_group_permissions" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "group_id" integer NOT NULL REFERENCES "auth_group" ("id") DEFERRABLE INITIALLY DEFERRED, "permission_id" integer NOT NULL REFERENCES "auth_permission" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: auth_permission
CREATE TABLE "auth_permission" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "content_type_id" integer NOT NULL REFERENCES "django_content_type" ("id") DEFERRABLE INITIALLY DEFERRED, "codename" varchar(100) NOT NULL, "name" varchar(255) NOT NULL);

-- table: billing_bankaccount
CREATE TABLE "billing_bankaccount" ("id" smallint unsigned NOT NULL PRIMARY KEY CHECK ("id" >= 0), "bank_name" varchar(100) NOT NULL, "account_number" varchar(50) NOT NULL, "account_holder" varchar(150) NOT NULL, CONSTRAINT "single_bank_account" CHECK ("id" = 1));

-- table: billing_invoice
CREATE TABLE "billing_invoice" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "month" smallint unsigned NOT NULL CHECK ("month" >= 0), "year" smallint unsigned NOT NULL CHECK ("year" >= 0), "room_fee" decimal NOT NULL, "electric_fee" decimal NOT NULL, "water_fee" decimal NOT NULL, "total_amount" decimal NOT NULL, "status" varchar(20) NOT NULL, "due_date" date NOT NULL, "created_at" datetime NOT NULL, "contract_id" bigint NOT NULL REFERENCES "rooms_contract" ("id") DEFERRABLE INITIALLY DEFERRED, "utility_reading_id" bigint NULL REFERENCES "billing_utilityreading" ("id") DEFERRABLE INITIALLY DEFERRED, "reminded_at" date NULL, "electric_unit_price" decimal NOT NULL, "note" text NOT NULL, "water_unit_price" decimal NOT NULL, CONSTRAINT "unique_contract_month_year_invoice" UNIQUE ("contract_id", "month", "year"));

-- table: billing_invoicedraft
CREATE TABLE "billing_invoicedraft" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "month" smallint unsigned NOT NULL CHECK ("month" >= 0), "year" smallint unsigned NOT NULL CHECK ("year" >= 0), "room_fee" decimal NOT NULL, "electric_unit_price" decimal NULL, "water_unit_price" decimal NULL, "old_electric" decimal NULL, "new_electric" decimal NULL, "old_water" decimal NULL, "new_water" decimal NULL, "service_items" text NOT NULL CHECK ((JSON_VALID("service_items") OR "service_items" IS NULL)), "due_date" date NULL, "note" text NOT NULL, "revision" integer unsigned NOT NULL CHECK ("revision" >= 0), "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "contract_id" bigint NOT NULL REFERENCES "rooms_contract" ("id") DEFERRABLE INITIALLY DEFERRED, "invoice_id" bigint NULL UNIQUE REFERENCES "billing_invoice" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "unique_contract_period_draft" UNIQUE ("contract_id", "month", "year"), CONSTRAINT "draft_valid_month" CHECK (("month" >= 1 AND "month" <= 12)), CONSTRAINT "draft_valid_year" CHECK (("year" >= 2000 AND "year" <= 2100)));

-- table: billing_invoiceservice
CREATE TABLE "billing_invoiceservice" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "quantity" integer unsigned NOT NULL CHECK ("quantity" >= 0), "subtotal" decimal NOT NULL, "invoice_id" bigint NOT NULL REFERENCES "billing_invoice" ("id") DEFERRABLE INITIALLY DEFERRED, "service_id" bigint NULL REFERENCES "billing_service" ("id") DEFERRABLE INITIALLY DEFERRED, "description" varchar(255) NOT NULL, "unit_price" decimal NULL, CONSTRAINT "unique_invoice_service" UNIQUE ("invoice_id", "service_id"));

-- table: billing_payment
CREATE TABLE "billing_payment" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "paid_date" date NOT NULL, "method" varchar(20) NOT NULL, "invoice_id" bigint NOT NULL REFERENCES "billing_invoice" ("id") DEFERRABLE INITIALLY DEFERRED, "note" text NOT NULL, "amount" decimal NOT NULL);

-- table: billing_paymentnotice
CREATE TABLE "billing_paymentnotice" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "note" text NOT NULL, "status" varchar(20) NOT NULL, "reject_reason" text NOT NULL, "created_at" datetime NOT NULL, "processed_at" datetime NULL, "invoice_id" bigint NOT NULL REFERENCES "billing_invoice" ("id") DEFERRABLE INITIALLY DEFERRED, "payment_id" bigint NULL UNIQUE REFERENCES "billing_payment" ("id") DEFERRABLE INITIALLY DEFERRED, "processed_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "tenant_id" bigint NOT NULL REFERENCES "accounts_tenant" ("id") DEFERRABLE INITIALLY DEFERRED, "amount" decimal NULL);

-- table: billing_service
CREATE TABLE "billing_service" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(100) NOT NULL, "unit_price" decimal NOT NULL);

-- table: billing_utilityrate
CREATE TABLE "billing_utilityrate" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "electric_price" decimal NOT NULL, "effective_date" date NOT NULL, "water_price" decimal NOT NULL);

-- table: billing_utilityreading
CREATE TABLE "billing_utilityreading" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "month" smallint unsigned NOT NULL CHECK ("month" >= 0), "year" smallint unsigned NOT NULL CHECK ("year" >= 0), "old_electric" decimal NOT NULL, "new_electric" decimal NOT NULL, "old_water" decimal NOT NULL, "new_water" decimal NOT NULL, "room_id" bigint NOT NULL REFERENCES "rooms_room" ("id") DEFERRABLE INITIALLY DEFERRED, "contract_id" bigint NULL REFERENCES "rooms_contract" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: django_admin_log
CREATE TABLE "django_admin_log" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "object_id" text NULL, "object_repr" varchar(200) NOT NULL, "action_flag" smallint unsigned NOT NULL CHECK ("action_flag" >= 0), "change_message" text NOT NULL, "content_type_id" integer NULL REFERENCES "django_content_type" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "action_time" datetime NOT NULL);

-- table: django_content_type
CREATE TABLE "django_content_type" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "app_label" varchar(100) NOT NULL, "model" varchar(100) NOT NULL);

-- table: django_migrations
CREATE TABLE "django_migrations" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "app" varchar(255) NOT NULL, "name" varchar(255) NOT NULL, "applied" datetime NOT NULL);

-- table: django_session
CREATE TABLE "django_session" ("session_key" varchar(40) NOT NULL PRIMARY KEY, "session_data" text NOT NULL, "expire_date" datetime NOT NULL);

-- table: rooms_checkoutrecord
CREATE TABLE "rooms_checkoutrecord" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "checkout_date" date NOT NULL, "deposit_held" decimal NOT NULL, "deposit_deducted" decimal NOT NULL, "deposit_refunded" decimal NOT NULL, "note" varchar(500) NOT NULL, "room_condition" varchar(20) NOT NULL, "created_at" datetime NOT NULL, "contract_id" bigint NOT NULL UNIQUE REFERENCES "rooms_contract" ("id") DEFERRABLE INITIALLY DEFERRED, "created_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: rooms_contract
CREATE TABLE "rooms_contract" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "start_date" date NOT NULL, "end_date" date NOT NULL, "deposit" decimal NOT NULL, "status" varchar(20) NOT NULL, "room_id" bigint NOT NULL REFERENCES "rooms_room" ("id") DEFERRABLE INITIALLY DEFERRED, "checkout_date" date NULL, "initial_electric" decimal NULL, "initial_water" decimal NULL, "monthly_rent" decimal NULL, "prorate_first_month" bool NOT NULL, "use_default_services" bool NOT NULL, "previous_contract_id" bigint NULL REFERENCES "rooms_contract" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: rooms_contract_services
CREATE TABLE "rooms_contract_services" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "contract_id" bigint NOT NULL REFERENCES "rooms_contract" ("id") DEFERRABLE INITIALLY DEFERRED, "service_id" bigint NOT NULL REFERENCES "billing_service" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: rooms_contractrenewal
CREATE TABLE "rooms_contractrenewal" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "old_end_date" date NOT NULL, "new_end_date" date NOT NULL, "renewed_on" date NOT NULL, "note" varchar(255) NOT NULL, "created_at" datetime NOT NULL, "contract_id" bigint NOT NULL REFERENCES "rooms_contract" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: rooms_contracttenant
CREATE TABLE "rooms_contracttenant" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "is_representative" bool NOT NULL, "contract_id" bigint NOT NULL REFERENCES "rooms_contract" ("id") DEFERRABLE INITIALLY DEFERRED, "tenant_id" bigint NOT NULL REFERENCES "accounts_tenant" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "unique_contract_tenant" UNIQUE ("contract_id", "tenant_id"));

-- table: rooms_depositentry
CREATE TABLE "rooms_depositentry" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "kind" varchar(20) NOT NULL, "amount" decimal NOT NULL, "occurred_on" date NOT NULL, "method" varchar(10) NOT NULL, "note" varchar(500) NOT NULL, "reference" char(32) NOT NULL UNIQUE, "created_at" datetime NOT NULL, "contract_id" bigint NOT NULL REFERENCES "rooms_contract" ("id") DEFERRABLE INITIALLY DEFERRED, "created_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "related_contract_id" bigint NULL REFERENCES "rooms_contract" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "positive_deposit_entry" CHECK ("amount" > '0'));

-- table: rooms_room
CREATE TABLE "rooms_room" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "room_number" varchar(10) NOT NULL UNIQUE, "area" decimal NULL, "max_occupants" integer unsigned NOT NULL CHECK ("max_occupants" >= 0), "status" varchar(20) NOT NULL, "floor" smallint unsigned NOT NULL CHECK ("floor" >= 0), "amenities" varchar(255) NOT NULL, "description" text NOT NULL, "price" decimal NOT NULL);

-- table: rooms_roomphoto
CREATE TABLE "rooms_roomphoto" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "image" varchar(100) NOT NULL, "caption" varchar(150) NOT NULL, "position" smallint unsigned NOT NULL CHECK ("position" >= 0), "created_at" datetime NOT NULL, "room_id" bigint NOT NULL REFERENCES "rooms_room" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: rooms_viewingappointment
CREATE TABLE "rooms_viewingappointment" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "code" varchar(10) NOT NULL UNIQUE, "visitor_name" varchar(100) NOT NULL, "visitor_phone" varchar(20) NOT NULL, "appointment_date" date NOT NULL, "slot" varchar(10) NOT NULL, "note" varchar(255) NOT NULL, "status" varchar(20) NOT NULL, "owner_note" varchar(255) NOT NULL, "created_at" datetime NOT NULL, "room_id" bigint NOT NULL REFERENCES "rooms_room" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: support_announcement
CREATE TABLE "support_announcement" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "title" varchar(200) NOT NULL, "content" text NOT NULL, "is_active" bool NOT NULL, "created_at" datetime NOT NULL, "created_by_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: support_maintenancerequest
CREATE TABLE "support_maintenancerequest" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "title" varchar(200) NOT NULL, "category" varchar(20) NOT NULL, "description" text NOT NULL, "priority" varchar(20) NOT NULL, "preferred_date" date NULL, "preferred_slot" varchar(10) NOT NULL, "contact_method" varchar(20) NOT NULL, "status" varchar(20) NOT NULL, "owner_note" text NOT NULL, "expected_done" date NULL, "created_at" datetime NOT NULL, "resolved_at" datetime NULL, "room_id" bigint NOT NULL REFERENCES "rooms_room" ("id") DEFERRABLE INITIALLY DEFERRED, "tenant_id" bigint NOT NULL REFERENCES "accounts_tenant" ("id") DEFERRABLE INITIALLY DEFERRED);

-- index: accounts_user_groups_group_id_bd11a704
CREATE INDEX "accounts_user_groups_group_id_bd11a704" ON "accounts_user_groups" ("group_id");

-- index: accounts_user_groups_user_id_52b62117
CREATE INDEX "accounts_user_groups_user_id_52b62117" ON "accounts_user_groups" ("user_id");

-- index: accounts_user_groups_user_id_group_id_59c0b32f_uniq
CREATE UNIQUE INDEX "accounts_user_groups_user_id_group_id_59c0b32f_uniq" ON "accounts_user_groups" ("user_id", "group_id");

-- index: accounts_user_user_permissions_permission_id_113bb443
CREATE INDEX "accounts_user_user_permissions_permission_id_113bb443" ON "accounts_user_user_permissions" ("permission_id");

-- index: accounts_user_user_permissions_user_id_e4f0a161
CREATE INDEX "accounts_user_user_permissions_user_id_e4f0a161" ON "accounts_user_user_permissions" ("user_id");

-- index: accounts_user_user_permissions_user_id_permission_id_2ab516c2_uniq
CREATE UNIQUE INDEX "accounts_user_user_permissions_user_id_permission_id_2ab516c2_uniq" ON "accounts_user_user_permissions" ("user_id", "permission_id");

-- index: auth_group_permissions_group_id_b120cbf9
CREATE INDEX "auth_group_permissions_group_id_b120cbf9" ON "auth_group_permissions" ("group_id");

-- index: auth_group_permissions_group_id_permission_id_0cd325b0_uniq
CREATE UNIQUE INDEX "auth_group_permissions_group_id_permission_id_0cd325b0_uniq" ON "auth_group_permissions" ("group_id", "permission_id");

-- index: auth_group_permissions_permission_id_84c5c92e
CREATE INDEX "auth_group_permissions_permission_id_84c5c92e" ON "auth_group_permissions" ("permission_id");

-- index: auth_permission_content_type_id_2f476e4b
CREATE INDEX "auth_permission_content_type_id_2f476e4b" ON "auth_permission" ("content_type_id");

-- index: auth_permission_content_type_id_codename_01ab375a_uniq
CREATE UNIQUE INDEX "auth_permission_content_type_id_codename_01ab375a_uniq" ON "auth_permission" ("content_type_id", "codename");

-- index: billing_invoice_contract_id_f1f80c0a
CREATE INDEX "billing_invoice_contract_id_f1f80c0a" ON "billing_invoice" ("contract_id");

-- index: billing_invoice_utility_reading_id_a6a2cac3
CREATE INDEX "billing_invoice_utility_reading_id_a6a2cac3" ON "billing_invoice" ("utility_reading_id");

-- index: billing_invoicedraft_contract_id_7887732f
CREATE INDEX "billing_invoicedraft_contract_id_7887732f" ON "billing_invoicedraft" ("contract_id");

-- index: billing_invoiceservice_invoice_id_a5975f36
CREATE INDEX "billing_invoiceservice_invoice_id_a5975f36" ON "billing_invoiceservice" ("invoice_id");

-- index: billing_invoiceservice_service_id_12dee82b
CREATE INDEX "billing_invoiceservice_service_id_12dee82b" ON "billing_invoiceservice" ("service_id");

-- index: billing_payment_invoice_id_998dd3c5
CREATE INDEX "billing_payment_invoice_id_998dd3c5" ON "billing_payment" ("invoice_id");

-- index: billing_paymentnotice_invoice_id_46efadcf
CREATE INDEX "billing_paymentnotice_invoice_id_46efadcf" ON "billing_paymentnotice" ("invoice_id");

-- index: billing_paymentnotice_processed_by_id_b0c2ba05
CREATE INDEX "billing_paymentnotice_processed_by_id_b0c2ba05" ON "billing_paymentnotice" ("processed_by_id");

-- index: billing_paymentnotice_tenant_id_c22d9f27
CREATE INDEX "billing_paymentnotice_tenant_id_c22d9f27" ON "billing_paymentnotice" ("tenant_id");

-- index: billing_utilityreading_contract_id_05d48cf1
CREATE INDEX "billing_utilityreading_contract_id_05d48cf1" ON "billing_utilityreading" ("contract_id");

-- index: billing_utilityreading_room_id_9949f614
CREATE INDEX "billing_utilityreading_room_id_9949f614" ON "billing_utilityreading" ("room_id");

-- index: django_admin_log_content_type_id_c4bce8eb
CREATE INDEX "django_admin_log_content_type_id_c4bce8eb" ON "django_admin_log" ("content_type_id");

-- index: django_admin_log_user_id_c564eba6
CREATE INDEX "django_admin_log_user_id_c564eba6" ON "django_admin_log" ("user_id");

-- index: django_content_type_app_label_model_76bd3d3b_uniq
CREATE UNIQUE INDEX "django_content_type_app_label_model_76bd3d3b_uniq" ON "django_content_type" ("app_label", "model");

-- index: django_session_expire_date_a5c62663
CREATE INDEX "django_session_expire_date_a5c62663" ON "django_session" ("expire_date");

-- index: notice_status_created_idx
CREATE INDEX "notice_status_created_idx" ON "billing_paymentnotice" ("status", "created_at");

-- index: one_active_contract_per_room
CREATE UNIQUE INDEX "one_active_contract_per_room" ON "rooms_contract" ("room_id") WHERE "status" = 'hieu_luc';

-- index: one_contract_representative
CREATE UNIQUE INDEX "one_contract_representative" ON "rooms_contracttenant" ("contract_id") WHERE "is_representative";

-- index: one_pending_notice_per_invoice
CREATE UNIQUE INDEX "one_pending_notice_per_invoice" ON "billing_paymentnotice" ("invoice_id") WHERE "status" = 'cho_xac_nhan';

-- index: rooms_checkoutrecord_created_by_id_e7e6efa7
CREATE INDEX "rooms_checkoutrecord_created_by_id_e7e6efa7" ON "rooms_checkoutrecord" ("created_by_id");

-- index: rooms_contract_previous_contract_id_c6b32d35
CREATE INDEX "rooms_contract_previous_contract_id_c6b32d35" ON "rooms_contract" ("previous_contract_id");

-- index: rooms_contract_room_id_e1247ff7
CREATE INDEX "rooms_contract_room_id_e1247ff7" ON "rooms_contract" ("room_id");

-- index: rooms_contract_services_contract_id_8c73c4e9
CREATE INDEX "rooms_contract_services_contract_id_8c73c4e9" ON "rooms_contract_services" ("contract_id");

-- index: rooms_contract_services_contract_id_service_id_07327d82_uniq
CREATE UNIQUE INDEX "rooms_contract_services_contract_id_service_id_07327d82_uniq" ON "rooms_contract_services" ("contract_id", "service_id");

-- index: rooms_contract_services_service_id_bb498c03
CREATE INDEX "rooms_contract_services_service_id_bb498c03" ON "rooms_contract_services" ("service_id");

-- index: rooms_contractrenewal_contract_id_ffcc1a80
CREATE INDEX "rooms_contractrenewal_contract_id_ffcc1a80" ON "rooms_contractrenewal" ("contract_id");

-- index: rooms_contracttenant_contract_id_df09c431
CREATE INDEX "rooms_contracttenant_contract_id_df09c431" ON "rooms_contracttenant" ("contract_id");

-- index: rooms_contracttenant_tenant_id_64a834b0
CREATE INDEX "rooms_contracttenant_tenant_id_64a834b0" ON "rooms_contracttenant" ("tenant_id");

-- index: rooms_depositentry_contract_id_b3d88fb6
CREATE INDEX "rooms_depositentry_contract_id_b3d88fb6" ON "rooms_depositentry" ("contract_id");

-- index: rooms_depositentry_created_by_id_a54b7b7f
CREATE INDEX "rooms_depositentry_created_by_id_a54b7b7f" ON "rooms_depositentry" ("created_by_id");

-- index: rooms_depositentry_related_contract_id_ec964bec
CREATE INDEX "rooms_depositentry_related_contract_id_ec964bec" ON "rooms_depositentry" ("related_contract_id");

-- index: rooms_roomphoto_room_id_6324648b
CREATE INDEX "rooms_roomphoto_room_id_6324648b" ON "rooms_roomphoto" ("room_id");

-- index: rooms_viewingappointment_room_id_b313a239
CREATE INDEX "rooms_viewingappointment_room_id_b313a239" ON "rooms_viewingappointment" ("room_id");

-- index: support_announcement_created_by_id_6117e6b7
CREATE INDEX "support_announcement_created_by_id_6117e6b7" ON "support_announcement" ("created_by_id");

-- index: support_maintenancerequest_room_id_9b1c3de2
CREATE INDEX "support_maintenancerequest_room_id_9b1c3de2" ON "support_maintenancerequest" ("room_id");

-- index: support_maintenancerequest_status_10de8113
CREATE INDEX "support_maintenancerequest_status_10de8113" ON "support_maintenancerequest" ("status");

-- index: support_maintenancerequest_tenant_id_798d4aa1
CREATE INDEX "support_maintenancerequest_tenant_id_798d4aa1" ON "support_maintenancerequest" ("tenant_id");

-- index: unique_contract_period_reading
CREATE UNIQUE INDEX "unique_contract_period_reading" ON "billing_utilityreading" ("contract_id", "month", "year") WHERE "contract_id" IS NOT NULL;

-- index: unique_legacy_room_period_reading
CREATE UNIQUE INDEX "unique_legacy_room_period_reading" ON "billing_utilityreading" ("room_id", "month", "year") WHERE "contract_id" IS NULL;
