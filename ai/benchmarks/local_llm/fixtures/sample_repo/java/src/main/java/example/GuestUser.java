package example;

public class GuestUser extends NamedUser {
    public GuestUser(String name) {
        super(name);
    }

    public String greeting() {
        return "Hello, " + getName();
    }
}
