# Errors for independent review (check both predictions and source annotations)

- Any adult at my address okay to accept and sign, or does it need to be specifically me?
  Gold: ['delivery_tracking']  Predicted: ['payments']
- Is it required that the name on the order be the one signing, or can another adult do it?
  Gold: ['delivery_tracking']  Predicted: ['receipts_invoices']
- These boots pinch my dog's toes; can I exchange them?
  Gold: ['returns_refunds', 'size_fit']  Predicted: ['size_fit']
- The paw boots are too narrow, so I'd like to swap the pair.
  Gold: ['returns_refunds', 'size_fit']  Predicted: ['size_fit']
- The snow boots are squeezing my dog's paws -- can I trade them for a wider pair?
  Gold: ['returns_refunds', 'size_fit']  Predicted: ['size_fit']
- These paw booties run way too small on my pup; I need to send them back and exchange.
  Gold: ['returns_refunds', 'size_fit']  Predicted: ['returns_refunds', 'size_fit', 'order_changes']
- My dog's toes are getting pinched in these boots. Want to swap for bigger ones.
  Gold: ['returns_refunds', 'size_fit']  Predicted: ['size_fit']
- Too narrow across the top of the paw on these boots -- exchange process please?
  Gold: ['returns_refunds', 'size_fit']  Predicted: ['size_fit']
- These don't fit right, rubbing raw on my dog's feet. Happy to send back for a different size.
  Gold: ['returns_refunds', 'size_fit']  Predicted: ['returns_refunds', 'size_fit', 'order_changes']
- Sizing was off and the boot is tight around the ankle. Do you allow exchanges?
  Gold: ['returns_refunds', 'size_fit']  Predicted: ['size_fit']
- My lab can't wear these, they pinch his toes badly. Looking to return and get the next size up.
  Gold: ['returns_refunds', 'size_fit']  Predicted: ['returns_refunds', 'size_fit', 'order_changes']
- Can I return the unopened carrier and get a copy of its receipt?
  Gold: ['returns_refunds', 'receipts_invoices']  Predicted: ['receipts_invoices']
- The pet carrier is still sealed in the box -- how do I start a return and can you email me another copy of the receipt for it?
  Gold: ['returns_refunds', 'receipts_invoices']  Predicted: ['returns_refunds']
- Please send me a duplicate receipt and take back the carrier I never opened.
  Gold: ['returns_refunds', 'receipts_invoices']  Predicted: ['receipts_invoices']
- I'd like to ship the unopened carrier back home. Do you also reissue receipts? I need one for that purchase.
  Gold: ['returns_refunds', 'receipts_invoices']  Predicted: ['returns_refunds']
- Returning the carrier (unused, factory sealed) plus needing the paperwork reprinted -- what's the process?
  Gold: ['returns_refunds', 'receipts_invoices']  Predicted: ['returns_refunds']
- Can u get the carrier back from me and resend the invoice please? It was never even unboxed.
  Gold: ['returns_refunds', 'receipts_invoices']  Predicted: ['returns_refunds']
- Two things: authorize a return on the sealed carrier, and give me a second copy of its purchase receipt.
  Gold: ['returns_refunds', 'receipts_invoices']  Predicted: ['returns_refunds']
- I bought a carrier but never cracked the seal, so I want to return it -- and could you forward me the receipt again?
  Gold: ['returns_refunds', 'receipts_invoices']  Predicted: ['returns_refunds']
- How do I return an unopened carrier, and where can I get a reprint of the sales receipt for it?
  Gold: ['returns_refunds', 'receipts_invoices']  Predicted: ['returns_refunds']
- I want to return the tunnel and correct the review I posted about it.
  Gold: ['returns_refunds', 'reviews_feedback']  Predicted: ['reviews_feedback']
- Can I send the play tunnel back and edit my earlier public feedback?
  Gold: ['returns_refunds', 'reviews_feedback']  Predicted: ['reviews_feedback']
- I need to send back the agility tunnel and also revise the public review I left for it.
  Gold: ['returns_refunds', 'reviews_feedback']  Predicted: ['reviews_feedback']
- Can you process a return on the play tunnel? While you're at it, I want to change my posted feedback about that item.
  Gold: ['returns_refunds', 'reviews_feedback']  Predicted: ['returns_refunds']
- Please take back the cat tunnel order. Also, how do I go about correcting the rating and comments I published?
  Gold: ['returns_refunds', 'reviews_feedback']  Predicted: ['reviews_feedback']
- The tunnel needs to be exchanged — and please update my existing customer review since my experience changed.
  Gold: ['returns_refunds', 'reviews_feedback']  Predicted: ['reviews_feedback']
- Returning the exercise tunnel here. Could you also help me amend the star rating and text on my earlier review?
  Gold: ['returns_refunds', 'reviews_feedback']  Predicted: ['reviews_feedback']
- Send me a return label for the tunnel; additionally, I posted feedback about it and need to fix what I said.
  Gold: ['returns_refunds', 'reviews_feedback']  Predicted: ['returns_refunds']
- I'd like the harness measurements and details of warranty coverage for the fastener.
  Gold: ['size_fit', 'warranty_repairs']  Predicted: ['warranty_repairs']
- What range of neck sizes does that harness cover, and does the warranty include the buckle if it fails?
  Gold: ['size_fit', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Need the neck measurement specs for the harness plus info on whether the clasp is warrantied.
  Gold: ['size_fit', 'warranty_repairs']  Predicted: ['size_fit']
- Does this harness fit a 16 to 20 inch neck? And is the fastening hardware covered under warranty claims?
  Gold: ['size_fit', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Harness sizing question: which neck girths work? Second, warranty details on the buckle specifically.
  Gold: ['size_fit', 'warranty_repairs']  Predicted: ['size_fit']
- Im looking for the neck circumference range on the harness and wanna know if the buckle falls under warranty coverage
  Gold: ['size_fit', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Could you tell me the adjustable neck range for the harness, and whether repairs or replacements for the buckle are covered by warranty?
  Gold: ['size_fit', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Between what neck sizes does that harness adjust, and if the buckle breaks am I able to make a warranty claim on it?
  Gold: ['size_fit', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Which boot width fits a broad paw, and can the spring coupon be used on it?
  Gold: ['size_fit', 'promotions']  Predicted: ['promotions']
- I'd like help with paw-width sizing and whether the seasonal offer applies.
  Gold: ['size_fit', 'promotions']  Predicted: ['promotions']
- My dog has wide paws -- which width of those boots should I pick, and does the spring promo code work on them?
  Gold: ['size_fit', 'promotions']  Predicted: ['promotions']
- Boot sizing for a broad paw, plus whether the seasonal coupon applies to that item.
  Gold: ['size_fit', 'promotions']  Predicted: ['promotions']
- Do you have a wider boot option for fat paws? Wondering too if the spring sale discount stacks with it.
  Gold: ['size_fit', 'promotions']  Predicted: ['promotions']
- Which boot size covers a wide paw print? And can I use the current seasonal offer on the purchase?
  Gold: ['size_fit', 'promotions']  Predicted: ['promotions']
- Need help picking boot width for chunky paws -- also, is the spring coupon valid for these?
  Gold: ['size_fit', 'promotions']  Predicted: ['promotions']
- For a broad-footed pup, what width boot fits best, and would the seasonal promotion be honored on it?
  Gold: ['size_fit', 'promotions']  Predicted: ['promotions']
- Are these boots available in a wide width for big paws? Asking whether the spring deal can be applied.
  Gold: ['size_fit', 'promotions']  Predicted: ['promotions']
- Sizing question: which width handles a wide paw? And does the seasonal offer exclude these boots or not?
  Gold: ['size_fit', 'promotions']  Predicted: ['promotions']
- The carrier has not scanned my package, and my card shows two settled charges.
  Gold: ['delivery_tracking', 'payments']  Predicted: ['payments']
- Please check the missing shipment scan and the duplicated payment.
  Gold: ['delivery_tracking', 'payments']  Predicted: ['delivery_tracking']
- My tracking page still says no scan from the carrier, and somehow I got charged twice on the same order.
  Gold: ['delivery_tracking', 'payments']  Predicted: ['payments']
- Two things: the shipment hasn't been picked up by the shipping company yet, and my bank statement lists a duplicate settled payment.
  Gold: ['delivery_tracking', 'payments']  Predicted: ['delivery_tracking']
- It's been days with zero carrier movement on my parcel — plus I see two identical charges posted to my card.
  Gold: ['delivery_tracking', 'payments']  Predicted: ['payments']
- Where's my package? Nothing scanned in. Also why does my account show the order paid for twice?
  Gold: ['delivery_tracking', 'payments']  Predicted: ['payments']
- No delivery scan showing and a double charge cleared on my credit card. Can someone sort both out?
  Gold: ['delivery_tracking', 'payments']  Predicted: ['payments']
- Tracking is stuck at label created with no carrier acceptance, and there are 2 completed transactions for one purchase.
  Gold: ['delivery_tracking', 'payments']  Predicted: ['delivery_tracking']
- I'm worried because my money left the account twice while the box never even hit the carrier's system.
  Gold: ['delivery_tracking', 'payments']  Predicted: ['delivery_tracking']
- Package status hasn't budged (no carrier handoff) and my Visa shows the total debited two times, both settled.
  Gold: ['delivery_tracking', 'payments']  Predicted: ['payments']
- The parcel went to a locker, but I cannot sign in to see the collection notice.
  Gold: ['delivery_tracking', 'account_access']  Predicted: ['delivery_tracking']
- I need help locating the locker parcel and recovering access to my profile.
  Gold: ['delivery_tracking', 'account_access']  Predicted: ['delivery_tracking']
- Got a notice that my box was left in a pickup locker, but I can't log into my account to open it.
  Gold: ['delivery_tracking', 'account_access']  Predicted: ['delivery_tracking']
- Help needed on two fronts: locating the parcel sitting in the locker and getting back into my profile.
  Gold: ['delivery_tracking', 'account_access']  Predicted: ['delivery_tracking']
- The driver dropped it at an automated locker and now my password won't work so I can't view the collection details.
  Gold: ['delivery_tracking', 'account_access']  Predicted: ['delivery_tracking']
- My shipment is held at a parcel locker, and I've lost access to the login that has the pickup code.
  Gold: ['delivery_tracking', 'account_access']  Predicted: ['delivery_tracking']
- Can you tell me which locker my package went to? I also can't sign in anymore to check myself.
  Gold: ['delivery_tracking', 'account_access']  Predicted: ['account_access']
- Parcel marked delivered to a locker unit, but my account lockout means I can't read the notification inside.
  Gold: ['delivery_tracking', 'account_access']  Predicted: ['delivery_tracking']
- Stuck between a package waiting in some kiosk locker and a profile I suddenly cannot access — need both fixed.
  Gold: ['delivery_tracking', 'account_access']  Predicted: ['delivery_tracking']
- It got put in a collection locker, and since I can't get past the login screen I have no idea where or what code.
  Gold: ['delivery_tracking', 'account_access']  Predicted: ['account_access']
- Where is the parcel carrying my repaired fountain, and what warranty remains after servicing?
  Gold: ['delivery_tracking', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Please locate the serviced unit's shipment and explain its remaining repair coverage.
  Gold: ['delivery_tracking', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Any update on where the box with my serviced water fountain is? And how much warranty time is left post-repair?
  Gold: ['delivery_tracking', 'warranty_repairs']  Predicted: ['warranty_repairs']
- When will the repaired pump/fountain shipment arrive, and does the service reset or shorten my warranty?
  Gold: ['delivery_tracking', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Locate the parcel carrying my fixed pet fountain, please — also curious what repair guarantee still applies.
  Gold: ['delivery_tracking', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Shipment for the serviced unit seems slow; can you check its location and tell me the warranty terms after servicing?
  Gold: ['delivery_tracking', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Where's my fountain that came back from repair? Tracking would help. Also want to know if coverage continues.
  Gold: ['delivery_tracking', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Please confirm the courier position of my repaired item and explain any leftover warranty on the work done.
  Gold: ['delivery_tracking', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Two questions: current whereabouts of the parcel with my maintained fountain, and the extent of post-service warranty.
  Gold: ['delivery_tracking', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Please put the company name on the invoice and change the delivery contact on my pending purchase.
  Gold: ['receipts_invoices', 'order_changes']  Predicted: ['order_changes']
- I need a corrected billing document and a different recipient contact before fulfillment.
  Gold: ['receipts_invoices', 'order_changes']  Predicted: ['receipts_invoices']
- Could you reissue the billing doc with our business name listed, and swap the contact person on the order that hasn't shipped?
  Gold: ['receipts_invoices', 'order_changes']  Predicted: ['receipts_invoices']
- Need the invoice corrected to show the company instead of me, plus a new delivery phone/email before it goes out.
  Gold: ['receipts_invoices', 'order_changes']  Predicted: ['receipts_invoices']
- Please amend the paperwork name field and change who the carrier should call about the pending order.
  Gold: ['receipts_invoices', 'order_changes']  Predicted: ['order_changes']
- My receipt/invoice needs the employer's name added, and I want a different recipient contact on the unfulfilled purchase.
  Gold: ['receipts_invoices', 'order_changes']  Predicted: ['receipts_invoices']
- Update the billing document details and also edit the drop-off contact info while the order is still processing.
  Gold: ['receipts_invoices', 'order_changes']  Predicted: ['receipts_invoices']
- Add the LLC name to the itemized bill, and replace the delivery contact since the coworker won't be there.
  Gold: ['receipts_invoices', 'order_changes']  Predicted: ['delivery_tracking', 'receipts_invoices']
- Before fulfillment: fix the name on the invoice, and put my neighbor as the alternate contact for handoff.
  Gold: ['receipts_invoices', 'order_changes']  Predicted: ['receipts_invoices']
- Paperwork shows the wrong payer name — please correct it — and switch the phone number tied to the incoming delivery.
  Gold: ['receipts_invoices', 'order_changes']  Predicted: ['payments']
- Can the invoice show my business name, and where can I see the points ledger?
  Gold: ['receipts_invoices', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- I'd like a company receipt and access to my rewards transaction history.
  Gold: ['receipts_invoices', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Please put my LLC name on the receipt and show me where my points history is.
  Gold: ['receipts_invoices', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- I need an itemized invoice listing our business, plus a view of my loyalty accruals.
  Gold: ['receipts_invoices', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Can you reissue the purchase doc with my company info? Also wondering how to check redeemed rewards.
  Gold: ['receipts_invoices', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Looking for a copy of the bill addressed to my firm and access to the rewards ledger screen.
  Gold: ['receipts_invoices', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Our bookkeeper needs the invoice under the business name; separately, where do I see earned points?
  Gold: ['receipts_invoices', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Would like the packing slip/invoice to reflect our company and the transaction log for membership points.
  Gold: ['receipts_invoices', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Need the tax receipt renamed to my business entity and the full points statement visible.
  Gold: ['receipts_invoices', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Company-name invoice please, and can you point me to the loyalty activity page showing every point change?
  Gold: ['receipts_invoices', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- The scale will not turn on, and my card was charged more than the confirmed total.
  Gold: ['product_defect', 'payments']  Predicted: ['payments']
- I need help with a nonworking device and an incorrect settled payment amount.
  Gold: ['product_defect', 'payments']  Predicted: ['payments']
- Pet scale won't power up at all, plus my statement shows a charge higher than what I authorized at checkout.
  Gold: ['product_defect', 'payments']  Predicted: ['payments']
- Device is dead out of the box and I got billed twice basically -- needs sorting.
  Gold: ['product_defect', 'payments']  Predicted: ['payments']
- Non-working scale plus an overcharge on my card. Who fixes both?
  Gold: ['product_defect', 'payments']  Predicted: ['payments']
- Nothing happens when I press power on the new scale. On top of that my payment went through for more than expected.
  Gold: ['product_defect', 'payments']  Predicted: ['payments']
- Scale seems defective, zero response. Also there's a discrepancy between the confirmed total and what hit my bank.
  Gold: ['product_defect', 'payments']  Predicted: ['payments']
- It never booted up and the final charge was off from the receipt total. Please advise on both issues.
  Gold: ['product_defect', 'payments']  Predicted: ['payments']
- Won't switch on. Card also got charged above the amount i agreed to at purchase.
  Gold: ['product_defect', 'payments']  Predicted: ['payments']
- Are the refill pads available, and how much is postage for a dozen packs?
  Gold: ['shipping_fees', 'stock_availability']  Predicted: ['shipping_fees']
- Please check pad inventory and the delivery charge for a bulk purchase.
  Gold: ['shipping_fees', 'stock_availability']  Predicted: ['delivery_tracking', 'shipping_fees']
- Stock check please: refill pads. And how do shipping charges look for buying 12 packs at once?
  Gold: ['shipping_fees', 'stock_availability']  Predicted: ['shipping_fees']
- Can u tell me pad availability plus the freight/handling fee for a case of twelve?
  Gold: ['shipping_fees', 'stock_availability']  Predicted: ['shipping_fees']
- Before I order a dozen refill-pad packs, is there enough inventory and what's the total shipping?
  Gold: ['shipping_fees', 'stock_availability']  Predicted: ['stock_availability']
- Are the replacement pads sellable right now, or sold out? Curious about the delivery rate for a bulk lot too.
  Gold: ['shipping_fees', 'stock_availability']  Predicted: ['delivery_tracking', 'stock_availability']
- Need two things: whether refill pads can be reserved in quantity, and the per-order shipping charge for twelve packs.
  Gold: ['shipping_fees', 'stock_availability']  Predicted: ['shipping_fees']
- Is there a residential delivery surcharge, and can I pay with a prepaid card?
  Gold: ['shipping_fees', 'payments']  Predicted: ['shipping_fees']
- I need the home-delivery fee and confirmation that prepaid debit payment is accepted.
  Gold: ['shipping_fees', 'payments']  Predicted: ['shipping_fees']
- What does it cost to ship to a home address versus a pickup point, and will you take a prepaid Visa card at checkout?
  Gold: ['shipping_fees', 'payments']  Predicted: ['shipping_fees']
- Is there an added surcharge for residential drop-off? Also, can my gift-card-style prepaid debit work as payment?
  Gold: ['shipping_fees', 'payments']  Predicted: ['shipping_fees']
- Tell me the home delivery fee and confirm prepaid debit cards are accepted before I pay.
  Gold: ['shipping_fees', 'payments']  Predicted: ['payments']
- Residential delivery extra charge? And does your system process a non-reloadable prepaid card?
  Gold: ['shipping_fees', 'payments']  Predicted: ['shipping_fees']
- How much is the doorstep delivery add-on, and can i checkout using a prepaid card instead of my bank card?
  Gold: ['shipping_fees', 'payments']  Predicted: ['shipping_fees']
- I want the shipping price for a house address plus verification that prepaid debit is a valid payment option.
  Gold: ['shipping_fees', 'payments']  Predicted: ['shipping_fees']
- Does delivering to a residence tack on fees? Second question: is prepaid card payment supported here?
  Gold: ['shipping_fees', 'payments']  Predicted: ['shipping_fees']
- Quote me the residential delivery surcharge and let me know if a one-time-use prepaid card will go through.
  Gold: ['shipping_fees', 'payments']  Predicted: ['shipping_fees']
- What is the gate made from, and do metal gates carry an extra delivery fee?
  Gold: ['shipping_fees', 'product_information']  Predicted: ['shipping_fees']
- I need the barrier's material details and any product-specific postage surcharge.
  Gold: ['shipping_fees', 'product_information']  Predicted: ['shipping_fees']
- What material is the pet gate built out of, and is there heavier-item shipping cost for metal gates?
  Gold: ['shipping_fees', 'product_information']  Predicted: ['shipping_fees']
- Give me the barrier's construction details plus any extra postage charged specifically for steel gates.
  Gold: ['shipping_fees', 'product_information']  Predicted: ['shipping_fees']
- Is the gate aluminum or something else, and do oversize metal gates get hit with a delivery surcharge?
  Gold: ['shipping_fees', 'product_information']  Predicted: ['shipping_fees']
- Curious about what the gate is made from and how much shipping adds on for the metal version.
  Gold: ['shipping_fees', 'product_information']  Predicted: ['shipping_fees']
- Metal gate material specs please, along with the handling fee that applies to those items.
  Gold: ['shipping_fees', 'product_information']  Predicted: ['shipping_fees']
- Does the gate use wood, plastic, or metal? And is there a special freight charge tied to metal gates?
  Gold: ['shipping_fees', 'product_information']  Predicted: ['shipping_fees']
- Want to know the composition of the barrier and whether its weight bumps up the shipping price.
  Gold: ['shipping_fees', 'product_information']  Predicted: ['shipping_fees']
- What's the gate constructed from, and how much extra does it cost to ship the heavier metal style?
  Gold: ['shipping_fees', 'product_information']  Predicted: ['size_fit', 'shipping_fees']
- Can I redeem my points and apply the newsletter coupon together?
  Gold: ['promotions', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Would rewards redemption and the email promotion work in the same checkout?
  Gold: ['promotions', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Am I allowed to burn loyalty points and use the coupon from the newsletter on one order?
  Gold: ['promotions', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Does stacking work between rewards redemption and the promotional email code at checkout?
  Gold: ['promotions', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Can both apply in the same transaction -- my member points and the mailer discount?
  Gold: ['promotions', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- I've got a newsletter promo code and some points saved up; are those combinable or either/or?
  Gold: ['promotions', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Will the site let me redeem reward balance alongside the advertised email offer, or no stacking?
  Gold: ['promotions', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Points plus the newsletter coupon together at payment -- is that permitted?
  Gold: ['promotions', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Trying to figure out if the loyalty redemption and the promotion code exclude each other in cart.
  Gold: ['promotions', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- If i cash in membership rewards can I still punch in the coupon sent by email, or does one block the other?
  Gold: ['promotions', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- I cannot access my profile, and the emailed discount says it has expired.
  Gold: ['promotions', 'account_access']  Predicted: ['promotions']
- Please help with my login and check the expiration of the promotional code.
  Gold: ['promotions', 'account_access']  Predicted: ['promotions']
- I can't log into my account anymore and the promo code in my email is showing as expired.
  Gold: ['promotions', 'account_access']  Predicted: ['account_access']
- My profile won't open — also, does that discount code from the newsletter still work or is it past its date?
  Gold: ['promotions', 'account_access']  Predicted: ['promotions']
- Locked out of my account and I think the coupon they emailed me already hit its expiration. Can someone check?
  Gold: ['promotions', 'account_access']  Predicted: ['promotions']
- Need help getting back into my profile plus verifying whether the promotional code has an end date on it.
  Gold: ['promotions', 'account_access']  Predicted: ['promotions']
- The discount link says expired and now I cant access my accound either. What do I do?
  Gold: ['promotions', 'account_access']  Predicted: ['promotions', 'loyalty_rewards']
- How do I recover login access? And while you're at it, confirm the expiry window on that emailed offer code.
  Gold: ['promotions', 'account_access']  Predicted: ['promotions']
- Both issues here: my account authentication is failing, and the sale code sent to me appears time-limited. Which do we fix first?
  Gold: ['promotions', 'account_access']  Predicted: ['account_access']
- Sign-in is broken for me and I want to know if the promo code in the message is dead or just hasn't activated yet.
  Gold: ['promotions', 'account_access']  Predicted: ['promotions']
- Does a price adjustment change the points I earned on that purchase?
  Gold: ['price_adjustments', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- I'd like a price-drop credit and to understand its effect on my rewards balance.
  Gold: ['price_adjustments', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- If you refund me the difference on a price drop, do my loyalty points get recalculated too?
  Gold: ['price_adjustments', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- I'm requesting a price-adjustment credit and would like to know how it impacts the points on my rewards account.
  Gold: ['price_adjustments', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Will a post-purchase price reduction cut into the points I already banked for that order?
  Gold: ['price_adjustments', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Hoping for a price-drop credit; curious whether my membership balance adjusts along with it.
  Gold: ['price_adjustments', 'loyalty_rewards']  Predicted: ['price_adjustments']
- Does getting money back for a lower price mean my earned rewards change? Asking about both things.
  Gold: ['price_adjustments', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- I want the price protection credit applied — but what happens to the loyalty accrual tied to that purchase?
  Gold: ['price_adjustments', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Price fell after I bought it so Id like a credit, and also need clarity on wether my points stay the same.
  Gold: ['price_adjustments', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Two-part question: eligibility for a price-drop adjustment, and the downstream effect on my rewards total.
  Gold: ['price_adjustments', 'loyalty_rewards']  Predicted: ['loyalty_rewards']
- Please cancel my pending litter mat and assess a price-drop claim for last month's crate.
  Gold: ['price_adjustments', 'order_changes']  Predicted: ['price_adjustments']
- I need one unfulfilled purchase stopped and a separate earlier purchase reviewed for price protection.
  Gold: ['price_adjustments', 'order_changes']  Predicted: ['price_adjustments']
- I need one upcoming order stopped before fulfillment plus a review of an older purchase for price protection.
  Gold: ['price_adjustments', 'order_changes']  Predicted: ['price_adjustments']
- Please pull the pending mat shipment and check whether last month's crate qualifies for a price adjustment.
  Gold: ['price_adjustments', 'order_changes']  Predicted: ['price_adjustments']
- Stop the unshipped order today, and also file a claim since the crate's price went down after I paid full sticker.
  Gold: ['price_adjustments', 'order_changes']  Predicted: ['price_adjustments']
- Can you void the recent litter mat purchase thats still pending? Also wondering if I can get a credit on the earlier crate.
  Gold: ['price_adjustments', 'order_changes']  Predicted: ['returns_refunds', 'price_adjustments']
- Two requests: cancel my not-yet-shipped item, then evaluate the price difference on a prior order from last month.
  Gold: ['price_adjustments', 'order_changes']  Predicted: ['price_adjustments']
- Id like to halt the new order before it ships AND get reimbursed for the crate price dropping. Is that possbile?
  Gold: ['price_adjustments', 'order_changes']  Predicted: ['price_adjustments']
- Hold off on sending the mat and run a price-protection check on the crate from my previous purchase.
  Gold: ['price_adjustments', 'order_changes']  Predicted: ['price_adjustments']
- Is the lower-priced blue model in stock, and can its price support my adjustment request?
  Gold: ['price_adjustments', 'stock_availability']  Predicted: ['price_adjustments']
- Please check inventory of the cheaper color and its eligibility for a price-difference claim.
  Gold: ['price_adjustments', 'stock_availability']  Predicted: ['price_adjustments']
- Is the blue version still available at the reduced price, and would buying it now support a price-difference claim?
  Gold: ['price_adjustments', 'stock_availability']  Predicted: ['price_adjustments']
- Check stock on the cheaper colorway and let me know if that qualifies for a price adjustment.
  Gold: ['price_adjustments', 'stock_availability']  Predicted: ['price_adjustments']
- Do you have the lower-priced model in inventory right now? Asking because I may be eligible for a price-drop credit.
  Gold: ['price_adjustments', 'stock_availability']  Predicted: ['price_adjustments']
- Wanna know if the blue one is instock and whether its current pricing affects my adjustment request.
  Gold: ['price_adjustments', 'stock_availability']  Predicted: ['price_adjustments']
- Availability check on the discounted variant, plus confirmation on whether that supports filing a price-difference claim.
  Gold: ['price_adjustments', 'stock_availability']  Predicted: ['price_adjustments']
- Is the less expensive color currently purchasable? If so, does that help with a price protection credit?
  Gold: ['price_adjustments', 'stock_availability']  Predicted: ['price_adjustments']
- Need two answers: stock status of the blue SKU at the new price, and whether that makes my price adjustment viable.
  Gold: ['price_adjustments', 'stock_availability']  Predicted: ['price_adjustments']
- Cna you tell me if the cheaper color is in stock and how that plays into eligibility for a price-drop reimbursement?
  Gold: ['price_adjustments', 'stock_availability']  Predicted: ['price_adjustments']
- I cannot sign in, and I need to change the recipient on my unfulfilled purchase.
  Gold: ['order_changes', 'account_access']  Predicted: ['order_changes']
- Please restore my account access and correct the delivery recipient before packing.
  Gold: ['order_changes', 'account_access']  Predicted: ['order_changes']
- Locked out of my account and I need to swap the recipient name on an order that hasn't shipped yet.
  Gold: ['order_changes', 'account_access']  Predicted: ['order_changes']
- My login keeps failing — can you fix access so I can edit who's receiving my pending purchase?
  Gold: ['order_changes', 'account_access']  Predicted: ['order_changes']
- Need help two ways: recover my profile sign-in, then change the delivery contact on my open order before it goes out.
  Gold: ['order_changes', 'account_access']  Predicted: ['order_changes']
- I'm having trouble getting into my account and I also want to update the recipient details on a not-yet-fulfilled order.
  Gold: ['order_changes', 'account_access']  Predicted: ['order_changes']
- Password reset isn't working for me. Once that's sorted, please switch the person listed to receive my unshipped order.
  Gold: ['order_changes', 'account_access']  Predicted: ['order_changes']
- Can someone restore my account access? I also need to correct the recipient info on my current order before packing.
  Gold: ['order_changes', 'account_access']  Predicted: ['order_changes']
- Two issues: I cant log in, and I need to put a different recipient on the order I placed yesterday that's still processing.
  Gold: ['order_changes', 'account_access']  Predicted: ['order_changes']
- Please unlock my account (locked after too many tries) and edit the shipping recipient on my upcoming order.
  Gold: ['order_changes', 'account_access']  Predicted: ['order_changes']
- Can the feeder run offline, and does owner maintenance affect its warranty?
  Gold: ['product_information', 'warranty_repairs']  Predicted: ['warranty_repairs']
- I need the device's offline capabilities and the warranty rules for routine cleaning.
  Gold: ['product_information', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Does this feeder work without wifi, and will cleaning it myself void the warranty?
  Gold: ['product_information', 'warranty_repairs']  Predicted: ['warranty_repairs']
- I'd like to know if the device operates offline plus how routine upkeep plays with coverage terms.
  Gold: ['product_information', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Quick pair of questions: can it run when internet is down, and does owner-performed maintenance affect warranty status?
  Gold: ['product_information', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Is offline operation supported, and what are the warranty rules around regular self-cleaning?
  Gold: ['product_information', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Need specs on whether the unit functions with no connection, along with guidance on warranty and DIY maintenance.
  Gold: ['product_information', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Will the feeder keep working if my network drops? Also curious if servicing it on my own changes the warranty.
  Gold: ['product_information', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Tell me about offline capability and whether following the care/maintenance steps myself impacts warranty claims.
  Gold: ['product_information', 'warranty_repairs']  Predicted: ['warranty_repairs']
- Curious if it needs wifi at all to dispense food, and how doing routine cleaning at home affects the warranty.
  Gold: ['product_information', 'warranty_repairs']  Predicted: ['warranty_repairs']
- I need to cancel only one item and keep the rest of the purchase.
  Gold: ['order_changes']  Predicted: ['returns_refunds', 'order_changes']
- Can you delete a single line item instead of voiding all three products?
  Gold: ['order_changes']  Predicted: ['account_access']
- Is there a way to reschedule when the next subscription shipment gets placed?
  Gold: ['order_changes']  Predicted: ['order_changes', 'stock_availability']
- My refill delivery keeps arriving too early -- can I set it for later dates?
  Gold: ['order_changes']  Predicted: ['delivery_tracking', 'order_changes']
- Changeover: my sub box should go out the week after next rather than Monday.
  Gold: ['order_changes']  Predicted: ['delivery_tracking', 'order_changes']
- I changed my mind about canceling -- is my original order still recoverable?
  Gold: ['order_changes']  Predicted: ['returns_refunds', 'order_changes']
- My cat keeps shredding the couch after dark and I don't know why.
  Gold: ['other']  Predicted: ['product_defect']
- Why does my puppy circle before lying down every single night?
  Gold: ['other']  Predicted: ['product_information']
- What makes a dog suddenly become scared of the vacuum cleaner?
  Gold: ['other']  Predicted: ['product_information']
- Can we move this over to French? My English is rusty.
  Gold: ['other']  Predicted: ['account_access']
- Is there a way to switch the language of this thread to German?
  Gold: ['other']  Predicted: ['account_access']
- My dog got into some antifreeze under the sink, what do I do right now?
  Gold: ['other']  Predicted: ['product_defect']
- Cat licked a bit of bleach off the tile floor -- is that dangerous?
  Gold: ['other']  Predicted: ['product_defect', 'product_information']
- He ate part of a dryer sheet, should I be worried or call someone?
  Gold: ['other']  Predicted: ['product_defect', 'warranty_repairs']
- Puppy swallowed a mothball. What's the first thing I should do?
  Gold: ['other']  Predicted: ['product_defect']
- My parrot nibbled on fabric softener wipes. Need urgent guidance.
  Gold: ['other']  Predicted: ['product_defect']
- Dog chewed through a roach bait station, tell me what steps to take.
  Gold: ['other']  Predicted: ['product_defect', 'product_information']
- Kitten drank a little dish soap water. Is this an emergency?
  Gold: ['other']  Predicted: ['product_defect', 'product_information']
- Rabbit got into drain cleaner residue. What should I do immediately?
  Gold: ['other']  Predicted: ['product_defect', 'product_information']
- how do i get rid of a saved cc without checking out
  Gold: ['payments']  Predicted: ['order_changes']
- I see a small unfamiliar authorization from your store.
  Gold: ['payments']  Predicted: ['receipts_invoices']
- Saw an unfamiliar little authorization posted by your store, need to know why.
  Gold: ['payments']  Predicted: ['other']
- Got this small temp charge from your pet store showing up ahead of my purchase?
  Gold: ['payments']  Predicted: ['shipping_fees']
- does the adjustement include tax on the difference or not?
  Gold: ['price_adjustments']  Predicted: ['shipping_fees']
- Does your standing offer cover subscription orders too?
  Gold: ['promotions']  Predicted: ['loyalty_rewards']
- can subs use the ad price?
  Gold: ['promotions']  Predicted: ['loyalty_rewards']
- Can you send me something confirming I bought this without listing what it cost?
  Gold: ['receipts_invoices']  Predicted: ['price_adjustments']
- Can I rate a different color option than the one that shipped to me?
  Gold: ['reviews_feedback']  Predicted: ['delivery_tracking', 'order_changes']
- Are you limited to reviewing the exact itemization you paid for, or can other variants work?
  Gold: ['reviews_feedback']  Predicted: ['price_adjustments']
- With several sacks of food, is the fee calculated from overall weight?
  Gold: ['shipping_fees']  Predicted: ['size_fit', 'shipping_fees']
- It works great for my cat but I need to know if it slides under an airplane seat.
  Gold: ['size_fit']  Predicted: ['size_fit', 'product_information']
- Do I have to dig up the S/N before submitting a claim form?
  Gold: ['warranty_repairs']  Predicted: ['returns_refunds']