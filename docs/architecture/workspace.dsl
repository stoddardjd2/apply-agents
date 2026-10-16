workspace "apply-agents" "Local Camoufox + OpenAI computer-use job applier" {

    model {
        operator = person "Operator" "Configures profile/resume and runs apply or worker CLIs."

        openai = softwareSystem "OpenAI API" "Agents SDK computer-use model: screenshots in, UI actions out." "External"
        landed = softwareSystem "Landed API" "Sibling app: job claim queue, resume download, steps/artifacts, finish, Gmail OTP." "External"
        jobSites = softwareSystem "Job Boards / ATS" "Indeed, Glassdoor, Greenhouse, Lever, Ashby, Workday, JazzHR, and employer career sites." "External"
        nopecha = softwareSystem "NopeCHA" "Firefox addon + API for Turnstile, reCAPTCHA, Cloudflare challenges." "External"
        nonecap = softwareSystem "NoneCap" "hCaptcha token API used to inject solved tokens into pages." "External"

        computerUse = softwareSystem "apply-agents" "Applies to job URLs with a resume PDF using headed Camoufox driven by OpenAI computer use." {

            applyCli = container "Apply CLI" "Python" "Single-job apply from apply.config.json; login and NopeCHA cache helpers." "job-apply"
            workerCli = container "Worker CLI" "Python" "Polls Landed for claims, applies, reports steps/artifacts/finish." "job-worker"
            harness = container "Browser Harness" "Python" "Shared Camoufox lifecycle, agent loop, features, captcha, Landed callbacks." {
                applyConfig = component "Apply / Worker Config" "Loads apply.config.json, worker.config.json, salary enrich, blocklists." "Python"
                featureRegistry = component "Feature Registry" "Composes optional tools/prompts: form KB, learnings, signup, OTP." "Python"
                formKnowledge = component "Form Knowledge" "resolve_form_question + form_knowledge.json screening Q&A." "Python"
                learnings = component "Learnings" "Cross-run tips and hard-run memory in apply_learnings.json." "Python"
                accountSignup = component "Account Signup" "Prompt-only rules for employer account creation." "Python"
                verificationCode = component "Verification Code" "OTP function tool; polls Landed Gmail when in worker mode." "Python"
                prompts = component "Apply Prompts" "Core system and user instructions for the computer-use agent." "Python"
                agentRunner = component "Agent Runner" "OpenAI Agents SDK Agent + ComputerTool + Runner loop." "Python"
                camoufoxComputer = component "LocalCamoufoxComputer" "AsyncComputer: screenshots, click/type/scroll, resume attach, aggregator escape." "Python"
                captchaSolvers = component "Captcha Solvers" "NopeCHA addon arming and NoneCap hCaptcha solve/inject." "Python"
                landedClient = component "Landed Client" "HTTP client: claim, resume, steps, artifacts, finish, OTP poll." "Python"
                aggregator = component "Aggregator Escape" "Detects leaving Glassdoor/Indeed for an ATS host." "Python"
                costs = component "Cost Tracker" "Token usage to USD estimate written to costs.json." "Python"
                fillLog = component "Fill / Agent Log" "Filled-field ledger and turn logging for Landed Q&A." "Python"
            }
            localStore = container "Local File Store" "Filesystem" "Configs, JSON KB/learnings/costs, Camoufox profile, resume cache." "Files"
        }

        # Context-level relationships
        operator -> computerUse "Runs apply / worker"
        computerUse -> openai "Computer-use agent turns"
        computerUse -> landed "Claim jobs, report steps, poll OTP"
        computerUse -> jobSites "Browse and submit applications"
        computerUse -> nopecha "Solve Turnstile / reCAPTCHA"
        computerUse -> nonecap "Solve hCaptcha"

        # Container-level relationships
        operator -> applyCli "Runs manual apply / --login"
        operator -> workerCli "Runs claim loop"
        operator -> localStore "Edits configs and form KB answers"

        applyCli -> harness "run_local_apply"
        workerCli -> harness "run_local_apply with Landed callbacks"
        workerCli -> landed "Claim application + finish outcome"
        harness -> localStore "Reads/writes config, KB, profile, costs"
        harness -> openai "Screenshots and tool calls"
        harness -> jobSites "Camoufox browser session"
        harness -> nopecha "Addon + API"
        harness -> nonecap "hCaptcha tokens"
        harness -> landed "Steps, artifacts, OTP (via client)"

        # Component-level relationships
        applyConfig -> localStore "Load/merge config"
        featureRegistry -> formKnowledge "Registers"
        featureRegistry -> learnings "Registers"
        featureRegistry -> accountSignup "Registers"
        featureRegistry -> verificationCode "Registers"
        featureRegistry -> prompts "Appends fragments"
        agentRunner -> prompts "System/user prompts"
        agentRunner -> featureRegistry "Function tools"
        agentRunner -> camoufoxComputer "ComputerTool actions"
        agentRunner -> openai "Computer-use turns"
        camoufoxComputer -> jobSites "Browse and fill applications"
        camoufoxComputer -> captchaSolvers "Arm / solve before submit"
        camoufoxComputer -> aggregator "Detect ATS escape"
        captchaSolvers -> nopecha "Addon + API"
        captchaSolvers -> nonecap "hCaptcha tokens"
        landedClient -> landed "Bearer + X-Landed-Worker HTTP"
        verificationCode -> landedClient "Poll Gmail OTP"
        aggregator -> landedClient "escape_aggregator step"
        fillLog -> landedClient "Post fill steps"
        costs -> localStore "Append costs.json"
        formKnowledge -> localStore "form_knowledge.json"
        learnings -> localStore "apply_learnings.json"
        camoufoxComputer -> localStore "Profile, resume PDF, screenshots"
        applyCli -> applyConfig "Load apply.config.json"
        workerCli -> applyConfig "Load worker + per-job config"
        workerCli -> landedClient "Claim, resume, finish"
    }

    views {
        systemContext computerUse "SystemContext" {
            include *
            autoLayout lr
            description "Operator and external systems around apply-agents."
        }

        container computerUse "Containers" {
            include *
            autoLayout tb
            description "CLIs, shared harness, and local persistence."
        }

        component harness "Components" {
            include *
            autoLayout tb
            description "Components inside the shared browser harness."
        }

        styles {
            element "Person" {
                shape Person
                background #08427b
                color #ffffff
            }
            element "Software System" {
                background #1168bd
                color #ffffff
            }
            element "External" {
                background #999999
                color #ffffff
            }
            element "Container" {
                background #438dd5
                color #ffffff
            }
            element "Component" {
                background #85bbf0
                color #000000
            }
            element "Files" {
                shape Folder
                background #438dd5
                color #ffffff
            }
        }
    }
}
