package example;

public class WelcomeController {
    public String welcome(NamedUser user) {
        return "Welcome, " + user.getName();
    }
}
