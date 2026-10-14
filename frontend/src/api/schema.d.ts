export interface paths {
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/meta": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Meta */
        get: operations["meta_api_v1_meta_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/register": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Register */
        post: operations["register_api_v1_auth_register_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login */
        post: operations["login_api_v1_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Logout */
        post: operations["logout_api_v1_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Me */
        get: operations["me_api_v1_auth_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/change-password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Change Password */
        post: operations["change_password_api_v1_auth_change_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients/{pid}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Patient Extended */
        get: operations["patient_extended_api_v1_patients__pid__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Patient Patch */
        patch: operations["patient_patch_api_v1_patients__pid__patch"];
        trace?: never;
    };
    "/api/v1/patients/{pid}/support-needs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Put Support Needs */
        put: operations["put_support_needs_api_v1_patients__pid__support_needs_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients/{pid}/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Overview */
        get: operations["overview_api_v1_patients__pid__overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients/{pid}/caregivers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Caregivers */
        get: operations["list_caregivers_api_v1_patients__pid__caregivers_get"];
        put?: never;
        /** Create Caregiver */
        post: operations["create_caregiver_api_v1_patients__pid__caregivers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients/{pid}/caregivers/{cid}/link": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Link Caregiver */
        post: operations["link_caregiver_api_v1_patients__pid__caregivers__cid__link_post"];
        /** Unlink Caregiver */
        delete: operations["unlink_caregiver_api_v1_patients__pid__caregivers__cid__link_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/caregivers/{cid}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Caregiver */
        get: operations["get_caregiver_api_v1_caregivers__cid__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Patch Caregiver */
        patch: operations["patch_caregiver_api_v1_caregivers__cid__patch"];
        trace?: never;
    };
    "/api/v1/caregivers/{cid}/schedule": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Schedule */
        get: operations["get_schedule_api_v1_caregivers__cid__schedule_get"];
        /** Put Schedule */
        put: operations["put_schedule_api_v1_caregivers__cid__schedule_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/caregivers/{cid}/availability": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Availability */
        get: operations["get_availability_api_v1_caregivers__cid__availability_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/caregivers/{cid}/availability-overrides": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Add Override */
        post: operations["add_override_api_v1_caregivers__cid__availability_overrides_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/caregivers/{cid}/availability-overrides/{oid}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Override */
        post: operations["cancel_override_api_v1_caregivers__cid__availability_overrides__oid__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients/{pid}/activities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Activities */
        get: operations["list_activities_api_v1_patients__pid__activities_get"];
        put?: never;
        /** Create Activity */
        post: operations["create_activity_api_v1_patients__pid__activities_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients/{pid}/activities/series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Activity Series */
        post: operations["create_activity_series_api_v1_patients__pid__activities_series_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/activities/{aid}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Activity */
        get: operations["get_activity_api_v1_activities__aid__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Patch Activity */
        patch: operations["patch_activity_api_v1_activities__aid__patch"];
        trace?: never;
    };
    "/api/v1/activities/{aid}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Activity */
        post: operations["cancel_activity_api_v1_activities__aid__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/activities/{aid}/complete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Complete Activity */
        post: operations["complete_activity_api_v1_activities__aid__complete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/activities/{aid}/dependencies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Add Dependency */
        post: operations["add_dependency_api_v1_activities__aid__dependencies_post"];
        /** Delete Dependency */
        delete: operations["delete_dependency_api_v1_activities__aid__dependencies_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/activities/{aid}/assignments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Add Assignment */
        post: operations["add_assignment_api_v1_activities__aid__assignments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/assignments/{assignment_id}/request-confirmation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Assignment Request-Confirmation */
        post: operations["assignment_request_confirmation_api_v1_assignments__assignment_id__request_confirmation_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/assignments/{assignment_id}/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Assignment Confirm */
        post: operations["assignment_confirm_api_v1_assignments__assignment_id__confirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/assignments/{assignment_id}/decline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Assignment Decline */
        post: operations["assignment_decline_api_v1_assignments__assignment_id__decline_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/assignments/{assignment_id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Assignment Reject */
        post: operations["assignment_reject_api_v1_assignments__assignment_id__reject_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/assignments/{assignment_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Assignment Cancel */
        post: operations["assignment_cancel_api_v1_assignments__assignment_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/caregivers/{cid}/assignment-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Assignment History */
        get: operations["assignment_history_api_v1_caregivers__cid__assignment_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients/{pid}/caregivers/workload": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Caregiver Workloads */
        get: operations["caregiver_workloads_api_v1_patients__pid__caregivers_workload_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Patients */
        get: operations["list_patients_api_v1_patients_get"];
        put?: never;
        /** Create Patient */
        post: operations["create_patient_api_v1_patients_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients/{patient_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Patient */
        get: operations["get_patient_api_v1_patients__patient_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Patch Patient */
        patch: operations["patch_patient_api_v1_patients__patient_id__patch"];
        trace?: never;
    };
    "/api/v1/patients/{patient_id}/care-team": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Care Team */
        get: operations["care_team_api_v1_patients__patient_id__care_team_get"];
        put?: never;
        /** Add Team */
        post: operations["add_team_api_v1_patients__patient_id__care_team_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients/{patient_id}/care-team/{member_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Remove Team */
        delete: operations["remove_team_api_v1_patients__patient_id__care_team__member_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/patients/{patient_id}/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** History */
        get: operations["history_api_v1_patients__patient_id__history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/demo/reset": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Demo Reset */
        post: operations["demo_reset_api_v1_admin_demo_reset_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** ActivityIn */
        ActivityIn: {
            /** Title */
            title: string;
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Category
             * @default OTHER
             */
            category: string;
            /**
             * Scheduled Start
             * Format: date-time
             */
            scheduled_start: string;
            /**
             * Scheduled End
             * Format: date-time
             */
            scheduled_end: string;
            /** Deadline */
            deadline?: string | null;
            /**
             * Importance
             * @default MEDIUM
             * @enum {string}
             */
            importance: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
            /**
             * Requires Caregiver
             * @default true
             */
            requires_caregiver: boolean;
            /** Required Support */
            required_support?: string[];
            /**
             * Buffer Before Min
             * @default 0
             */
            buffer_before_min: number;
            /**
             * Buffer After Min
             * @default 0
             */
            buffer_after_min: number;
            /**
             * Location Note
             * @default
             */
            location_note: string;
        };
        /** ActivityPatch */
        ActivityPatch: {
            /** Title */
            title?: string | null;
            /** Description */
            description?: string | null;
            /** Category */
            category?: string | null;
            /** Scheduled Start */
            scheduled_start?: string | null;
            /** Scheduled End */
            scheduled_end?: string | null;
            /** Deadline */
            deadline?: string | null;
            /** Importance */
            importance?: ("LOW" | "MEDIUM" | "HIGH" | "CRITICAL") | null;
            /** Requires Caregiver */
            requires_caregiver?: boolean | null;
            /** Required Support */
            required_support?: string[] | null;
            /** Buffer Before Min */
            buffer_before_min?: number | null;
            /** Buffer After Min */
            buffer_after_min?: number | null;
            /** Location Note */
            location_note?: string | null;
        };
        /** AssignmentIn */
        AssignmentIn: {
            /**
             * Caregiver Id
             * Format: uuid
             */
            caregiver_id: string;
            /**
             * Role
             * @default PRIMARY
             * @enum {string}
             */
            role: "PRIMARY" | "BACKUP";
            /**
             * Confirm Now
             * @default false
             */
            confirm_now: boolean;
            /**
             * Scope
             * @default THIS
             * @enum {string}
             */
            scope: "THIS" | "FUTURE_IN_SERIES";
        };
        /** CancelIn */
        CancelIn: {
            /**
             * Reason
             * @default
             */
            reason: string;
        };
        /** CaregiverIn */
        CaregiverIn: {
            /** Name */
            name: string;
            /** Kind */
            kind: string;
            /**
             * Relationship
             * @default
             */
            relationship: string;
            /** User Id */
            user_id?: string | null;
            /** Phone */
            phone?: string | null;
            /** Capabilities */
            capabilities?: string[];
            /**
             * Max Activities Per Day
             * @default 3
             */
            max_activities_per_day: number;
            /**
             * Max Hours Per Week
             * @default 40
             */
            max_hours_per_week: number;
            /**
             * Notes
             * @default
             */
            notes: string;
            /**
             * Is Designated Backup
             * @default false
             */
            is_designated_backup: boolean;
        };
        /** CaregiverLinkIn */
        CaregiverLinkIn: {
            /**
             * Relationship
             * @default
             */
            relationship: string;
            /**
             * Is Designated Backup
             * @default false
             */
            is_designated_backup: boolean;
        };
        /** CaregiverPatch */
        CaregiverPatch: {
            /** Name */
            name?: string | null;
            /** Kind */
            kind?: string | null;
            /** Phone */
            phone?: string | null;
            /** Capabilities */
            capabilities?: string[] | null;
            /** Max Activities Per Day */
            max_activities_per_day?: number | null;
            /** Max Hours Per Week */
            max_hours_per_week?: number | null;
            /** Notes */
            notes?: string | null;
            /** Is Active */
            is_active?: boolean | null;
        };
        /** DeclineIn */
        DeclineIn: {
            /** Reason */
            reason: string;
        };
        /** DependencyIn */
        DependencyIn: {
            /**
             * Depends On Activity Id
             * Format: uuid
             */
            depends_on_activity_id: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** LoginIn */
        LoginIn: {
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Password */
            password: string;
        };
        /** OverrideIn */
        OverrideIn: {
            /**
             * Start At
             * Format: date-time
             */
            start_at: string;
            /**
             * End At
             * Format: date-time
             */
            end_at: string;
            /**
             * Status
             * @enum {string}
             */
            status: "UNAVAILABLE" | "AVAILABLE";
            /**
             * Reason
             * @enum {string}
             */
            reason: "WORK" | "ILLNESS" | "TRAVEL" | "PERSONAL" | "EMERGENCY" | "OTHER";
            /**
             * Note
             * @default
             */
            note: string;
        };
        /** PasswordIn */
        PasswordIn: {
            /** Current Password */
            current_password: string;
            /** New Password */
            new_password: string;
        };
        /** PatientCorePatch */
        PatientCorePatch: {
            /** Name */
            name?: string | null;
            /** Birth Year */
            birth_year?: number | null;
            /** Care Notes */
            care_notes?: string | null;
            /** Clinical Notes */
            clinical_notes?: string | null;
            /** Mobility Level */
            mobility_level?: ("INDEPENDENT" | "NEEDS_AID" | "WHEELCHAIR" | "BEDBOUND") | null;
            /** Language Pref */
            language_pref?: string | null;
        };
        /** PatientIn */
        PatientIn: {
            /** Name */
            name: string;
            /** Birth Year */
            birth_year?: number | null;
            /**
             * Care Notes
             * @default
             */
            care_notes: string;
            /**
             * Clinical Notes
             * @default
             */
            clinical_notes: string;
            /**
             * Mobility Level
             * @default INDEPENDENT
             */
            mobility_level: string;
            /**
             * Language Pref
             * @default en
             */
            language_pref: string;
        };
        /** PatientPatch */
        PatientPatch: {
            /** Name */
            name?: string | null;
            /** Birth Year */
            birth_year?: number | null;
            /** Care Notes */
            care_notes?: string | null;
            /** Clinical Notes */
            clinical_notes?: string | null;
            /** Mobility Level */
            mobility_level?: string | null;
            /** Language Pref */
            language_pref?: string | null;
        };
        /** ReasonIn */
        ReasonIn: {
            /**
             * Reason
             * @default
             */
            reason: string;
        };
        /** RegisterIn */
        RegisterIn: {
            /** Name */
            name: string;
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Password */
            password: string;
        };
        /** ScheduleIn */
        ScheduleIn: {
            /** Windows */
            windows: {
                [key: string]: unknown;
            }[];
        };
        /** SeriesIn */
        SeriesIn: {
            /** Title */
            title: string;
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Category
             * @default OTHER
             */
            category: string;
            /**
             * Scheduled Start
             * Format: date-time
             */
            scheduled_start: string;
            /**
             * Scheduled End
             * Format: date-time
             */
            scheduled_end: string;
            /** Deadline */
            deadline?: string | null;
            /**
             * Importance
             * @default MEDIUM
             * @enum {string}
             */
            importance: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
            /**
             * Requires Caregiver
             * @default true
             */
            requires_caregiver: boolean;
            /** Required Support */
            required_support?: string[];
            /**
             * Buffer Before Min
             * @default 0
             */
            buffer_before_min: number;
            /**
             * Buffer After Min
             * @default 0
             */
            buffer_after_min: number;
            /**
             * Location Note
             * @default
             */
            location_note: string;
            /**
             * Recurrence
             * @enum {string}
             */
            recurrence: "DAILY" | "WEEKLY";
            /**
             * Interval
             * @default 1
             */
            interval: number;
            /** By Weekday */
            by_weekday?: number[] | null;
            /** Count */
            count?: number | null;
            /** Until */
            until?: string | null;
        };
        /** SupportNeedIn */
        SupportNeedIn: {
            /** Support Code */
            support_code: string;
            /**
             * Notes
             * @default
             */
            notes: string;
        };
        /** TeamIn */
        TeamIn: {
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Team Role */
            team_role: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    meta_api_v1_meta_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    register_api_v1_auth_register_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegisterIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    login_api_v1_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    logout_api_v1_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    me_api_v1_auth_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    change_password_api_v1_auth_change_password_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PasswordIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    patient_extended_api_v1_patients__pid__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    patient_patch_api_v1_patients__pid__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PatientCorePatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_support_needs_api_v1_patients__pid__support_needs_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SupportNeedIn"][];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    overview_api_v1_patients__pid__overview_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_caregivers_api_v1_patients__pid__caregivers_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_caregiver_api_v1_patients__pid__caregivers_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CaregiverIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    link_caregiver_api_v1_patients__pid__caregivers__cid__link_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pid: string;
                cid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CaregiverLinkIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    unlink_caregiver_api_v1_patients__pid__caregivers__cid__link_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pid: string;
                cid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_caregiver_api_v1_caregivers__cid__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                cid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    patch_caregiver_api_v1_caregivers__cid__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                cid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CaregiverPatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_schedule_api_v1_caregivers__cid__schedule_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                cid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_schedule_api_v1_caregivers__cid__schedule_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                cid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ScheduleIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_availability_api_v1_caregivers__cid__availability_get: {
        parameters: {
            query: {
                from: string;
                to: string;
            };
            header?: never;
            path: {
                cid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_override_api_v1_caregivers__cid__availability_overrides_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                cid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OverrideIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_override_api_v1_caregivers__cid__availability_overrides__oid__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                cid: string;
                oid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_activities_api_v1_patients__pid__activities_get: {
        parameters: {
            query?: {
                from?: string | null;
                to?: string | null;
                lifecycle_status?: string | null;
                category?: string | null;
                caregiver_id?: string | null;
                unconfirmed?: boolean;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path: {
                pid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_activity_api_v1_patients__pid__activities_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActivityIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_activity_series_api_v1_patients__pid__activities_series_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SeriesIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_activity_api_v1_activities__aid__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                aid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    patch_activity_api_v1_activities__aid__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                aid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActivityPatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_activity_api_v1_activities__aid__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                aid: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["CancelIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    complete_activity_api_v1_activities__aid__complete_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                aid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_dependency_api_v1_activities__aid__dependencies_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                aid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DependencyIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_dependency_api_v1_activities__aid__dependencies_delete: {
        parameters: {
            query: {
                depends_on_activity_id: string;
            };
            header?: never;
            path: {
                aid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_assignment_api_v1_activities__aid__assignments_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                aid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssignmentIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    assignment_request_confirmation_api_v1_assignments__assignment_id__request_confirmation_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                assignment_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ReasonIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    assignment_confirm_api_v1_assignments__assignment_id__confirm_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                assignment_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ReasonIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    assignment_decline_api_v1_assignments__assignment_id__decline_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                assignment_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["DeclineIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    assignment_reject_api_v1_assignments__assignment_id__reject_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                assignment_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ReasonIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    assignment_cancel_api_v1_assignments__assignment_id__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                assignment_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ReasonIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    assignment_history_api_v1_caregivers__cid__assignment_history_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                cid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    caregiver_workloads_api_v1_patients__pid__caregivers_workload_get: {
        parameters: {
            query: {
                from: string;
                to: string;
            };
            header?: never;
            path: {
                pid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_patients_api_v1_patients_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_patient_api_v1_patients_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PatientIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_patient_api_v1_patients__patient_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                patient_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    patch_patient_api_v1_patients__patient_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                patient_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PatientPatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    care_team_api_v1_patients__patient_id__care_team_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                patient_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_team_api_v1_patients__patient_id__care_team_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                patient_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TeamIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    remove_team_api_v1_patients__patient_id__care_team__member_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                patient_id: string;
                member_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    history_api_v1_patients__patient_id__history_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path: {
                patient_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    demo_reset_api_v1_admin_demo_reset_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
}
