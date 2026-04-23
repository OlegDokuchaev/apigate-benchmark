use crate::auth_client::AuthClient;

// Verifies the Bearer token, injects x-user-id / x-user-email, and strips
// `authorization` so downstream services never see the JWT.
#[apigate::hook]
pub async fn require_auth(ctx: &mut apigate::PartsCtx, auth: &AuthClient) -> apigate::HookResult {
    let token = ctx
        .header("authorization")
        .ok_or_else(|| apigate::ApigateError::unauthorized("missing authorization header"))?
        .to_string();

    let user = auth.verify(&token).await?;

    ctx.set_header("x-user-id", &user.user_id)?;
    ctx.set_header("x-user-email", &user.email)?;
    ctx.remove_header("authorization");
    Ok(())
}
