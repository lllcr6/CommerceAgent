# English RAG annotation review

121 authored questions. Source sections are explicitly selected; relevance is not inferred from keyword matches.
Offline canonical chunk IDs must be rebound to the deployed English index before live evaluation.
Development and held-out scenarios are grouped by primary evidence section. They share a synthetic authored corpus; this is not an independent production benchmark.

| ID | Split | Bucket | Question | Relevant chunk IDs |
| --- | --- | --- | --- | --- |
| EN001 | dev | A_policy | What is the standard return window, and can I try a harness on my dog? | 65, 54 |
| EN002 | dev | A_policy | Does the return clock start when I order or when the package arrives? | 65 |
| EN003 | dev | A_policy | How long is the litter box in-home trial? | 66, 54 |
| EN004 | dev | A_policy | My cat will not use the litter box. Are gently used units eligible for the trial? | 66 |
| EN005 | dev | A_policy | Can I return an opened pack of replacement filters just because I changed my mind? | 67 |
| EN006 | dev | A_policy | Do wrong or defective filters qualify for help even if they are open? | 67 |
| EN007 | dev | A_policy | Do I need authorization before mailing back a return? | 68, 55 |
| EN008 | dev | A_policy | Once a return is authorized, how long do I have to ship it? | 68 |
| EN009 | dev | A_policy | What is the return label fee for a harness that does not fit? | 69 |
| EN010 | dev | A_policy | Do I pay both the $25 and $4.95 return fees for a litter box shipment? | 69 |
| EN011 | dev | A_policy | Who pays return postage for a verified defective product? | 69 |
| EN012 | dev | A_policy | Do you refund original delivery charges when I simply change my mind? | 69 |
| EN013 | dev | A_policy | Will returning part of my order below $49 create a new outbound shipping charge? | 69 |
| EN014 | dev | A_policy | When do return inspection and bank refund posting happen? | 70 |
| EN015 | dev | A_policy | Can you send my refund to a different card? | 70 |
| EN016 | dev | A_policy | Does my refund use the original sale price or the full retail price? | 70 |
| EN017 | dev | A_policy | Can I exchange a harness for another size directly? | 71, 56 |
| EN018 | dev | A_policy | Is an unboxing video required to report transit damage? | 72, 75 |
| EN019 | dev | A_policy | Is seven days a hard cutoff for reporting a damaged item? | 72 |
| EN020 | dev | A_policy | Can a fountain defect still qualify for warranty after the return window? | 73, 76 |
| EN021 | dev | A_policy | What does the electronics warranty cover? | 76 |
| EN022 | dev | A_policy | Is chewing damage covered under the electronics warranty? | 76, 73 |
| EN023 | dev | A_policy | Who pays shipping for an approved warranty repair? | 77 |
| EN024 | dev | A_policy | Is there a guaranteed repair completion time? | 77 |
| EN025 | dev | A_policy | Where do you deliver in the United States? | 115, 57 |
| EN026 | dev | A_policy | Can you ship a dog bed to Hawaii or a PO box? | 115, 57 |
| EN027 | dev | A_policy | How much is standard shipping for an order under $49? | 116, 57 |
| EN028 | dev | A_policy | Does sales tax count toward free shipping? | 116 |
| EN029 | dev | A_policy | Is a $52 order with a $5 reward still eligible for free shipping? | 116 |
| EN030 | dev | A_policy | Do split packages each incur a shipping fee? | 116, 118 |
| EN031 | dev | A_policy | How do warehouse processing and shipping transit estimates differ? | 117, 58 |
| EN032 | dev | A_policy | Does a tracking label prove the carrier already has my order? | 118 |
| EN033 | dev | A_policy | What should I do if tracking says delivered but I cannot find the parcel? | 120, 61 |
| EN034 | dev | A_policy | My order has not shipped. Is cancellation guaranteed? | 119, 60 |
| EN035 | dev | A_policy | Will you substitute a different model if my item goes out of stock? | 121 |
| EN036 | heldout | A_policy | What payment methods are supported by store policy? | 113, 59 |
| EN037 | heldout | A_policy | Can I get an itemized receipt rather than a VAT invoice? | 114 |
| EN038 | heldout | A_policy | Can I give you my card security code in chat to investigate a charge? | 113 |
| EN039 | dev | A_policy | What are human-support hours and the first-response target? | 74 |
| EN040 | dev | A_policy | Does creating a ticket connect me to a live support agent? | 74 |
| EN041 | dev | A_policy | Does Paw Points cost money or enroll me in recurring shipments? | 105, 111 |
| EN042 | dev | A_policy | How many Paw Points does $24.99 of eligible paid merchandise earn? | 106 |
| EN043 | dev | A_policy | When do points post for an order delivered in multiple packages? | 106 |
| EN044 | heldout | A_policy | Can points pay for shipping or sales tax? | 107 |
| EN045 | heldout | A_policy | How much can I redeem in Paw Points on one order? | 107 |
| EN046 | dev | A_policy | When do unused points expire? | 108 |
| EN047 | dev | A_policy | What happens to points used on a refunded order? | 108, 70 |
| EN048 | dev | A_policy | Can I combine two promo codes and my points? | 109 |
| EN049 | dev | A_policy | Does the seven-day price-adjustment window start at delivery? | 110, 62 |
| EN050 | dev | A_policy | Do you price match another store or a flash sale? | 110, 62 |
| EN051 | dev | B_model | Does MH-LP50 connect to Wi-Fi or send app alerts? | 84, 79 |
| EN052 | dev | B_model | What cat weight range is listed for MH-LP100? | 85 |
| EN053 | dev | B_model | How much litter does MH-LP200 hold? | 86 |
| EN054 | dev | B_model | Which litter box is documented for a 23 lb cat? | 84, 85, 86 |
| EN055 | dev | B_model | Can kittens under six months use automatic cleaning on MH-LP100? | 85, 79 |
| EN056 | dev | B_model | Which replacement filters fit MH-W20? | 87, 103, 80 |
| EN057 | dev | B_model | Will MH-WF60 filters fit my MH-W20 fountain? | 104, 103 |
| EN058 | dev | B_model | Can MH-W40 and MH-W60 share a filter pack? | 104, 88, 89 |
| EN059 | dev | B_model | Does MH-W40 use UV sterilization? | 88 |
| EN060 | heldout | B_model | What material and capacity does MH-W60 have? | 89 |
| EN061 | dev | B_model | Can I wash the foam inside MH-DB30 in a washing machine? | 99, 82 |
| EN062 | dev | B_model | What dimensions does the large MH-DB30 bed have? | 99 |
| EN063 | dev | B_model | Which MH-DH20 size fits a dog with a 22-inch chest? | 97 |
| EN064 | dev | B_model | Can I choose MH-DH20 sizing from my dog's breed alone? | 97, 82 |
| EN065 | dev | B_model | Can MH-DH20 be used as a vehicle safety restraint? | 97 |
| EN066 | dev | B_model | How long is MH-DL10, and what dog weight is it intended for? | 98 |
| EN067 | dev | B_model | Is MH-DL10 suitable for tying my dog outside unattended? | 98 |
| EN068 | dev | B_model | Can the MH-SB20 bowl go in the dishwasher? | 100 |
| EN069 | dev | B_model | Does MH-SB20 guarantee prevention of bloat? | 100 |
| EN070 | dev | B_model | Is MH-DP10 a chew toy that I can leave with my dog? | 101 |
| EN071 | dev | B_model | Are MH-WB60 waste bags compostable or flushable? | 102 |
| EN072 | dev | B_model | How many waste bags and rolls are in MH-WB60? | 102 |
| EN073 | heldout | B_model | Can MH-FD10 feed wet food, and does it have an app? | 93, 81 |
| EN074 | dev | B_model | What works on MH-FD30 during a power outage? | 94 |
| EN075 | dev | B_model | Is the camera on MH-FD30 the same product as MH-CAM1? | 94, 95 |
| EN076 | heldout | B_model | Does MH-CAM1 require paid cloud recording? | 95 |
| EN077 | heldout | B_model | What local storage does MH-CAM1 support? | 95 |
| EN078 | dev | B_model | Can I wash the whole MH-NEST20 cat bed? | 96 |
| EN079 | heldout | B_model | How tall is MH-CT30, and what is its per-platform load limit? | 90 |
| EN080 | dev | B_model | Is MH-HP12 safe for unattended use or pets unable to move away? | 91 |
| EN081 | dev | B_model | How does MH-HP20 differ from MH-HP12? | 91, 92 |
| EN082 | dev | C_colloquial | My pup's harness is huge lol. Do I have to keep it? | 65, 71 |
| EN083 | dev | C_colloquial | Cat hates the robot after a month. Am I stuck with it? | 66 |
| EN084 | dev | C_colloquial | Wait, I used points and now there's shipping?? | 116, 107 |
| EN085 | dev | C_colloquial | It says label created but hasn't actually shipped, right? | 118 |
| EN086 | dev | C_colloquial | Can u ship this to an APO? | 115 |
| EN087 | dev | C_colloquial | Got the wrong filters n already opened em. Help? | 67 |
| EN088 | dev | C_colloquial | Fountain ain't pumping. What should I check first? | 80 |
| EN089 | dev | C_colloquial | My warmer smells burnt. Should I keep restarting it? | 78 |
| EN090 | dev | C_colloquial | I'm mad, the package says delivered but there's nothing here | 120, 61 |
| EN091 | dev | C_colloquial | I didn't film the unboxing. Can you still help with damage? | 72 |
| EN092 | dev | C_colloquial | Can I swap this for a medium without buying again? | 71, 56 |
| EN093 | dev | C_colloquial | I cancelled, so the money is already back, yeah? | 70 |
| EN094 | dev | C_colloquial | My dog chewed the power cord. Warranty covers that, no? | 76, 78 |
| EN095 | dev | C_colloquial | Can i hook the feeder up to just 5ghz wifi? | 81 |
| EN096 | dev | C_colloquial | Returning half my order. Will u claw back free delivery? | 69 |
| EN097 | dev | E_multi | Can I return MH-DH20 after a fit check, and what chest measurement selects medium? | 65, 97 |
| EN098 | dev | E_multi | If my cat rejects MH-LP100 on day 45, what trial applies and what is the return-label fee? | 66, 69 |
| EN099 | dev | E_multi | How do I clean MH-W20, and can I send back filters I have already used? | 87, 67 |
| EN100 | dev | E_multi | Which fountains share MH-WF60, and who pays postage if you sent the wrong filters? | 104, 69 |
| EN101 | dev | E_multi | Does MH-DB30 have the electronics warranty, and can I return it after checking fit? | 76, 65, 99 |
| EN102 | dev | E_multi | When do points post, and can using them remove free shipping eligibility? | 106, 107, 116 |
| EN103 | dev | E_multi | My MH-FD30 does not connect. What Wi-Fi band does it need and how do I reach a person? | 81, 74 |
| EN104 | dev | E_multi | Does a MH-W60 defect after 40 days mean I have no options? Explain returns versus warranty and repair shipping. | 73, 76, 77 |
| EN105 | heldout | E_multi | Compare offline MH-FD10 with MH-FD30 and say whether a paid subscription is required for camera recording. | 93, 94 |
| EN106 | dev | E_multi | How do price-adjustment and standard return deadlines differ? | 110, 65 |
| EN107 | dev | D_absent | What is the UL certification number for MH-HP12? | None |
| EN108 | dev | D_absent | What is the exact current price and live inventory of MH-DH20? | None |
| EN109 | heldout | D_absent | What is the serial number of the camera in my home? | None |
| EN110 | dev | D_absent | What is the exact motor torque in MH-LP200? | None |
| EN111 | heldout | D_absent | How many decibels does the MH-W20 pump produce? | None |
| EN112 | dev | D_absent | Which firmware version shipped on MH-FD30 last week? | None |
| EN113 | dev | D_absent | What is the exact return warehouse street address? | None |
| EN114 | dev | D_absent | What is my current Paw Points balance? | None |
| EN115 | dev | D_absent | What is the current tracking location of order someone-9999? | None |
| EN116 | dev | D_absent | Which exact date will my refund appear in my bank account? | None |
| EN117 | dev | D_absent | What is the annual revenue of Paw & Hearth? | None |
| EN118 | dev | D_absent | What antibiotic dose should I give my sick dog? | None |
| EN119 | heldout | D_absent | What is the maximum measured pull force rating in newtons for MH-DL10? | None |
| EN120 | dev | D_absent | What is the foam density in pounds per cubic foot for MH-DB30? | None |
| EN121 | heldout | D_absent | Which FCC ID is printed on MH-CAM1? | None |
